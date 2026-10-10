"""Durable, issuer-safe Results overlay for settled Match Winner publications.

Azure Table is the append-only serving sidecar. The canonical predictions release
and its original issued odds/ledger remain immutable during hourly status checks.
Each row can only originate from a deployed Match Winner pick + a provider-
confirmed terminal status. Per-day shards avoid the Azure 64-KiB string ceiling.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from .admin_storage import (
    AdminStorageUnavailable, UI_TABLE, _table, _storage_not_found,
    _encode_runtime_ui_payload, _decode_runtime_ui_payload,
)
from .match_status import runtime_settled_results, verified_terminal_statuses

_PARTITION = "settled-results-archive-v1"
_PUBLIC_SECTIONS = {"top_daily", "prime", "value", "doubles"}
_SHARDS = 4
_MAX_ROW_UTF16 = 60_000
_MAX_ARCHIVED_ROWS = 12_000
_PLAYER_KEYS = (
    "id", "name", "country", "country_code", "country_code2",
    "country_code3", "photo", "photo_url", "image", "image_url",
    "avatar", "rank",
)
_ROW_KEYS = (
    "event_id", "id", "scheduled_at", "date", "tour", "tournament",
    "tournament_id", "tournament_logo", "tournament_logo_url",
    "surface", "round", "competition", "prediction_family",
    "betting_day", "is_doubles",
)


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _identity(row: dict, publication: dict) -> str:
    event = str(row.get("event_id") or row.get("id") or "").strip()
    section = str(publication.get("section") or "").strip().lower()
    market = str(publication.get("market") or "match_winner").strip().lower()
    scope = str(publication.get("projection_scope") or "").strip().lower()
    metric = str(publication.get("projection_metric") or "").strip().lower()
    selection = str(publication.get("selection_id") or publication.get("winner_id") or "").strip()
    if not (event and section and market and selection):
        return ""
    return "|".join((event, section, market, scope, metric, selection))


def _archive_record(row: dict, publication: dict, generated_at: str) -> dict | None:
    if not isinstance(row, dict) or not isinstance(publication, dict):
        return None
    identity = _identity(row, publication)
    if not identity or str(publication.get("section") or "").lower() not in _PUBLIC_SECTIONS:
        return None
    if str(publication.get("market") or "match_winner").lower() != "match_winner":
        return None
    result = publication.get("result")
    if not isinstance(result, dict) or result.get("runtime_source") != "match_status_snapshot":
        return None
    if result.get("correct") not in (True, False) and not result.get("void"):
        return None
    scheduled = _time(row.get("scheduled_at") or row.get("date"))
    if scheduled is None:
        return None
    # Fail closed for later publications. A legacy deployed daily offer may
    # omit issued_at; its immutable morning feed generation must predate play.
    issued = _time(publication.get("issued_at")) if publication.get("issued_at") else None
    if publication.get("issued_at") and issued is None:
        return None
    if issued is None:
        if publication.get("runtime_publication_evidence") != "deployed_daily_offer_row":
            return None
        issued = _time(generated_at)
    if issued is None or issued > scheduled:
        return None
    player = lambda p: {k: deepcopy(v) for k, v in (p or {}).items() if k in _PLAYER_KEYS} if isinstance(p, dict) else {}
    stored = {k: deepcopy(row[k]) for k in _ROW_KEYS if k in row}
    stored["player1"] = player(row.get("player1"))
    stored["player2"] = player(row.get("player2"))
    stored["market_publications"] = [deepcopy(publication)]
    stored["runtime_result_overlay"] = True
    stored["archive_source"] = "verified_match_status_snapshot"
    return stored


def settled_archive_candidates(feed: dict, statuses: dict) -> list[dict]:
    """Materialize exclusively already deployed and verified terminal picks."""
    verified = verified_terminal_statuses(statuses)
    if not verified:
        return []
    # Historical feed rows are never reissued or archived as fresh picks.
    source = {**feed, "results": []}
    runtime = runtime_settled_results(source, verified)
    generated_at = str(feed.get("generated_at") or "")
    unique = {}
    for row in runtime:
        if not row.get("runtime_result_overlay"):
            continue
        for publication in row.get("market_publications") or []:
            stored = _archive_record(row, publication, generated_at)
            if stored is not None:
                unique[_identity(stored, stored["market_publications"][0])] = stored
    return list(unique.values())


def _slot(row: dict) -> tuple[str, str]:
    publication = row["market_publications"][0]
    key = _identity(row, publication)
    moment = _time(row.get("scheduled_at") or row.get("date"))
    if not key or moment is None:
        raise AdminStorageUnavailable("Invalid settled-results archive identity")
    bucket = int(sha256(key.encode("utf-8")).hexdigest()[:8], 16) % _SHARDS
    return f"{moment.date().isoformat()}-{bucket:02d}", key


def save_settled_results_archive(rows: list[dict]) -> dict:
    """Idempotent write + persisted readback, no provider calls or ledger edits."""
    groups = {}
    for row in rows:
        slot, key = _slot(row)
        groups.setdefault(slot, {})[key] = row
    if not groups:
        return {"eligible": 0, "added": 0, "updated": 0, "verified": True}
    try:
        table = _table(UI_TABLE)
        added = updated = 0
        for slot, incoming in sorted(groups.items()):
            try:
                previous = table.get_entity(partition_key=_PARTITION, row_key=slot)
                old = _decode_runtime_ui_payload(str(previous.get("payload") or ""))
                if not isinstance(old, dict) or old.get("schema") != 1 or not isinstance(old.get("rows"), dict):
                    raise AdminStorageUnavailable("Corrupt result archive; refusing overwrite")
                records = old["rows"]
            except Exception as exc:
                if isinstance(exc, AdminStorageUnavailable):
                    raise
                if not _storage_not_found(exc):
                    raise
                records = {}
            combined = dict(records)
            changed = False
            for key, row in incoming.items():
                if combined.get(key) != row:
                    if key in combined:
                        updated += 1
                    else:
                        added += 1
                    combined[key] = row
                    changed = True
            if not changed:
                continue
            encoded = _encode_runtime_ui_payload({"schema": 1, "rows": combined})
            if len(encoded.encode("utf-16-le")) > _MAX_ROW_UTF16:
                raise AdminStorageUnavailable("Result archive shard exceeded Azure property limit")
            table.upsert_entity({
                "PartitionKey": _PARTITION, "RowKey": slot,
                "payload": encoded,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, mode="replace")
            # The workflow is only successful when the newly issued Results are
            # durably readable. Silent 200s with missing rows must never pass.
            persisted = table.get_entity(partition_key=_PARTITION, row_key=slot)
            recovered = _decode_runtime_ui_payload(str(persisted.get("payload") or ""))
            if not isinstance(recovered, dict) or any(
                recovered.get("rows", {}).get(key) != row for key, row in incoming.items()
            ):
                raise AdminStorageUnavailable("Result archive persisted readback failed")
        return {"eligible": len(rows), "added": added, "updated": updated, "verified": True}
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to persist match results archive") from exc


def load_settled_results_archive() -> list[dict]:
    """Read durable Results; never infer settlements from unfinished matches."""
    try:
        table = _table(UI_TABLE)
        records = {}
        for item in table.query_entities(f"PartitionKey eq '{_PARTITION}'"):
            if len(records) > _MAX_ARCHIVED_ROWS:
                raise AdminStorageUnavailable("Result archive exceeds safe read limit")
            parsed = _decode_runtime_ui_payload(str(item.get("payload") or ""))
            if not isinstance(parsed, dict) or parsed.get("schema") != 1 or not isinstance(parsed.get("rows"), dict):
                raise AdminStorageUnavailable("Unreadable results archive shard")
            for key, row in parsed["rows"].items():
                if isinstance(row, dict) and row.get("market_publications"):
                    records[key] = row
        return list(records.values())
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load match results archive") from exc



def read_only_archive_category_counts(
    archived: list[dict], *, now: datetime | None = None,
) -> dict:
    """Aggregate-only category readback for diagnosing Results filters.

    No user, event or selection identifiers are returned; this function does
    not mutate the Azure archive or infer settlements.
    """
    from collections import Counter
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    bratislava = ZoneInfo("Europe/Bratislava")
    clock = (now or datetime.now(timezone.utc)).astimezone(bratislava)

    def day_key(moment: datetime) -> str:
        local = moment.astimezone(bratislava)
        if local.hour < 6:
            local -= timedelta(days=1)
        return local.date().isoformat()

    current_day = day_key(clock)
    by_section: Counter = Counter()
    all_sections: Counter = Counter()
    current_rows = selected_rows = mismatch = 0
    selected = {"top_daily", "value", "ace", "double_faults", "sets", "games"}
    for row in archived:
        if not isinstance(row, dict):
            continue
        scheduled = _time(row.get("scheduled_at") or row.get("date"))
        if scheduled is None:
            continue
        for publication in row.get("market_publications") or []:
            if not isinstance(publication, dict):
                continue
            result = publication.get("result")
            if not isinstance(result, dict) or (
                result.get("correct") not in (True, False) and not result.get("void")
            ):
                continue
            market = str(publication.get("market") or "").lower()
            section = {
                "aces": "ace", "double_faults": "double_faults",
                "sets": "sets", "games": "games",
            }.get(market, str(publication.get("section") or "").lower())
            if not section:
                continue
            all_sections[section] += 1
            if day_key(scheduled) != current_day:
                continue
            issued_snapshot = publication.get("issued_snapshot")
            issued_snapshot = issued_snapshot if isinstance(issued_snapshot, dict) else {}
            betting = row.get("betting")
            betting = betting if isinstance(betting, dict) else {}
            explicit = str(
                publication.get("betting_day")
                or issued_snapshot.get("betting_day")
                or row.get("betting_day")
                or betting.get("betting_day")
                or ""
            )
            # Mirrors the current Admin Today filter in web/app.js.
            if explicit and explicit != current_day:
                mismatch += 1
                continue
            current_rows += 1
            by_section[section] += 1
            if section in selected:
                selected_rows += 1
    return {
        "betting_day": current_day,
        "persisted_settled_all_time": sum(all_sections.values()),
        "persisted_by_category_all_time": dict(sorted(all_sections.items())),
        "persisted_settled_today": current_rows,
        "persisted_by_category_today": dict(sorted(by_section.items())),
        "persisted_selected_today": selected_rows,
        "excluded_betting_day_mismatch": mismatch,
        "selected_categories": sorted(selected),
    }


def merge_settled_results(feed: dict, archived: list[dict]) -> dict:
    """Overlay settled outcomes only, preserving canonical publication metadata."""
    out = dict(feed)
    rows = deepcopy(feed.get("results") or [])
    existing = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for publication in row.get("market_publications") or []:
            if not isinstance(publication, dict):
                continue
            key = _identity(row, publication)
            if key:
                existing[key] = publication
    for archived_row in archived:
        if not isinstance(archived_row, dict):
            continue
        pubs = archived_row.get("market_publications") or []
        if len(pubs) != 1 or not isinstance(pubs[0], dict):
            continue
        archived_pub = pubs[0]
        key = _identity(archived_row, archived_pub)
        if not key:
            continue
        if key in existing:
            incumbent = existing[key]
            previous = incumbent.get("result")
            previous = previous if isinstance(previous, dict) else {}
            if previous.get("correct") is None and not previous.get("void"):
                incumbent["result"] = deepcopy(archived_pub.get("result"))
            continue
        rows.append(deepcopy(archived_row))
        existing[key] = rows[-1]["market_publications"][0]
    rows.sort(key=lambda row: _time(row.get("scheduled_at") or row.get("date")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    out["results"] = rows
    return out
