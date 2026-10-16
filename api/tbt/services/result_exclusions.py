"""Admin-only reversible exclusions of *published settled bets* from public Results.

This never edits the immutable prediction ledger, the CDB, or provider evidence.
RowKey is the hash of a stable semantic bet identity. Alias sections sharing a
single selection collapse to one id, but distinct priced O/U lines never do.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re

from .admin_storage import _table, UI_TABLE, AdminStorageUnavailable
from .dashboard_kpis import _result_outcome

PARTITION = "result-test-exclusions-v1"
PUBLIC_SECTIONS = {"top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}
PROJECTION_MARKETS = {"aces", "double_faults", "sets", "games"}
_ID = re.compile(r"^[a-f0-9]{64}$")


def result_bet_id(row: dict, publication: dict) -> str:
    event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip().lower()
    market = str(publication.get("market") or "match_winner").strip().lower()
    scope = str(publication.get("projection_scope") or "").strip().lower()
    metric = str(publication.get("projection_metric") or "").strip().lower()
    selection = str(publication.get("selection_id") or publication.get("selection") or "").strip().lower()
    if not event:
        players = sorted(str((row.get(key) or {}).get("id") or (row.get(key) or {}).get("name") or "").lower().strip() for key in ("player1", "player2"))
        event = "|".join((str(row.get("scheduled_at") or ""), *players))
    if not event or not selection:
        return ""
    contract = ""
    if str(publication.get("price_contract") or "").lower() == "player_total_ou":
        contract = "|" + str(publication.get("ou_side") or "").strip().lower() + "|" + str(publication.get("market_line") or "").strip()
    elif market in {"sets", "games"}:
        contract = "|" + str(publication.get("projection_direction") or "").strip().lower() + "|" + str(publication.get("reference_projection") or "").strip()
    identity = "v1|" + "|".join((event, market, scope, metric, selection)) + contract
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _eligible(publication: dict) -> bool:
    if not isinstance(publication, dict) or not isinstance(publication.get("result"), dict):
        return False
    if publication.get("excluded_reason"):
        return False
    section = str(publication.get("section") or "").lower()
    market = str(publication.get("market") or "").lower()
    if section not in PUBLIC_SECTIONS and market not in {"aces", "double_faults"}:
        return False
    return bool(publication.get("issued_at") or (publication.get("result") or {}).get("runtime_source") == "match_status_snapshot")


def _admin_result_status(publication: dict) -> str:
    """Use the public Results outcome for statusless, already-settled bets."""
    outcome = _result_outcome(publication)
    if outcome != "pending":
        return outcome
    # Preserve the legacy admin label mapping for status-only records.
    result = publication.get("result") or {}
    return str(result.get("status") or result.get("outcome") or "")


def result_candidates(feed: dict) -> list[dict]:
    """Return complete page-independent admin inventory, no 50/100 row cap."""
    seen = {}
    for row in feed.get("results") or []:
        if not isinstance(row, dict):
            continue
        for publication in row.get("market_publications") or []:
            if not _eligible(publication):
                continue
            key = result_bet_id(row, publication)
            if not key or key in seen:
                continue
            result = publication.get("result") or {}
            selected = str(publication.get("selection") or publication.get("selection_id") or "")
            seen[key] = {
                "id": key,
                "event_id": str(row.get("event_id") or row.get("id") or row.get("match_id") or ""),
                "scheduled_at": str(row.get("scheduled_at") or row.get("date") or ""),
                "player1": str((row.get("player1") or {}).get("name") or ""),
                "player2": str((row.get("player2") or {}).get("name") or ""),
                "tour": str(row.get("tour") or ""),
                "section": str(publication.get("section") or ""),
                "market": str(publication.get("market") or ""),
                "selection": selected,
                "status": _admin_result_status(publication),
                "odds": publication.get("odds"),
            }
    return sorted(seen.values(), key=lambda r: (r["scheduled_at"], r["id"]), reverse=True)


def load_result_exclusions() -> set[str]:
    try:
        table = _table(UI_TABLE)
        keys = set()
        for entity in table.query_entities(f"PartitionKey eq '{PARTITION}'"):
            key = str(entity.get("RowKey") or "")
            if _ID.fullmatch(key) and entity.get("excluded") is True:
                keys.add(key)
        return keys
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to read result test exclusions") from exc


def set_result_exclusions(ids: list[str], excluded: bool, actor_id: str) -> dict:
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
        raise ValueError("invalid_result_batch_size")
    if not isinstance(excluded, bool) or not actor_id:
        raise ValueError("invalid_result_exclusion_request")
    if len(set(ids)) != len(ids) or any(not isinstance(k, str) or not _ID.fullmatch(k) for k in ids):
        raise ValueError("invalid_result_ids")
    now = datetime.now(timezone.utc).isoformat()
    try:
        table = _table(UI_TABLE)
        for key in ids:
            table.upsert_entity({
                "PartitionKey": PARTITION, "RowKey": key,
                "excluded": excluded, "reason": "admin_test_record",
                "actor_id": str(actor_id)[:100], "updated_at": now,
            }, mode="replace")
        persisted = load_result_exclusions()
        if any((key in persisted) != excluded for key in ids):
            raise AdminStorageUnavailable("Result exclusion readback did not match requested state")
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to update result test exclusions") from exc
    return {"updated": len(ids), "excluded": excluded, "excluded_total": len(persisted)}


def apply_result_exclusions(feed: dict, excluded_keys: set[str]) -> dict:
    if not excluded_keys:
        return feed
    out = dict(feed)
    rows = []
    for source in feed.get("results") or []:
        if not isinstance(source, dict):
            continue
        pubs = source.get("market_publications")
        if not isinstance(pubs, list):
            rows.append(source)
            continue
        kept = [p for p in pubs if not (isinstance(p, dict) and result_bet_id(source, p) in excluded_keys)]
        if kept:
            rows.append({**source, "market_publications": kept})
    out["results"] = rows
    return out
