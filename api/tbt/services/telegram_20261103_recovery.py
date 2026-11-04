"""One-shot, issuer-frozen 2026-11-03 Telegram Aces Results recovery.

NOT a CDB writer. Uses only the nine immutable 06:33 CET Telegram receipts,
persisted exact-ID match-status settlements, and a source-native Tennis API Pro
event+statistics witness for the missing Halys fixture. Abort on ambiguity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

from tbt.config import settings
from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.shared_budget import reserve as reserve_shared_api_budget
from tbt.providers.statistics import parse_statistics
from tbt.services.results_archive import (
    _identity, load_settled_results_archive, save_settled_results_archive,
    settled_archive_candidates,
)

DAY = "2026-11-03"
ISSUED_AT = "2026-11-03T05:33:27.415980+00:00"
# (event_id, player_id, displayed player, issued UTC start, frozen O/U line,
#  frozen statistical projection, frozen local odds, verified player aces).
# These fields were frozen by Telegram messages 730/731 (private ledger).
ISSUED_ACES = (
    ("17475617", "289146", "Giovanni Mpetshi Perricard", "14:10", 11.5, 12.61, 1.70, 11),
    ("17449516", "90798", "Quentin Halys", "10:00", 9.5, 11.00, 1.74, 17),
    ("17453204", "289106", "Coleman Wong", "07:10", 6.5, 8.16, 1.64, 6),
    ("17428202", "385485", "Ben Shelton", "18:00", 9.5, 11.41, 1.60, 6),
    ("17479726", "339453", "Lorenzo Claverie", "21:00", 5.5, 7.04, 1.66, 6),
    ("17452315", "221410", "Alycia Parks", "10:30", 3.5, 5.20, 1.62, None),
    ("17475619", "309071", "Jerome Kym", "11:10", 5.5, 7.22, 1.77, 8),
    ("17446377", "112747", "Leevi Saatela", "08:40", 3.5, 5.13, 1.80, 6),
    ("17477378", "215802", "Hernando Jose Escurra Isnardi", "16:00", 3.5, 4.58, 1.70, 8),
)
HALYS = "17449516"
EXPECTED_HALYS_HOME = "90798"
EXPECTED_HALYS_AWAY = "321789"


def _event(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Source-native event response unavailable")
    event = payload.get("event", payload)
    if not isinstance(event, dict):
        raise ValueError("Invalid source-native event envelope")
    return event


def _event_identity(event: dict, event_id: str) -> tuple[str, str, str, str]:
    home = event.get("homeTeam")
    away = event.get("awayTeam")
    if not isinstance(home, dict) or not isinstance(away, dict):
        raise ValueError("Source-native participants unavailable")
    p1, p2 = str(home.get("id") or ""), str(away.get("id") or "")
    if (str(event.get("id") or "") != event_id or not p1 or not p2 or p1 == p2
            or not str(home.get("name") or "") or not str(away.get("name") or "")):
        raise ValueError("Source-native event identity mismatch")
    return p1, p2, str(home["name"]), str(away["name"])


def _candidate_rows(snapshot: dict, event_details: dict[str, dict],
                    halys_stats: dict, checked_at: str) -> list[dict]:
    statuses = snapshot.get("statuses") if isinstance(snapshot, dict) else None
    if not isinstance(statuses, dict):
        raise ValueError("Missing previously persisted match-status snapshot")
    verified: dict[str, dict] = {}
    rows = []
    if len(ISSUED_ACES) != 9 or len({a[0] for a in ISSUED_ACES}) != 9:
        raise ValueError("Changed frozen Telegram ACE manifest")
    for event_id, selection, name, start, line, projection, odds, expected_aces in ISSUED_ACES:
        event = _event(event_details.get(event_id))
        p1, p2, n1, n2 = _event_identity(event, event_id)
        if selection not in {p1, p2}:
            raise ValueError("Provider event does not contain Telegram selected player")
        scheduled = f"{DAY}T{start}:00+00:00"
        if event_id == HALYS:
            if (p1 != EXPECTED_HALYS_HOME or p2 != EXPECTED_HALYS_AWAY
                    or n1.casefold() != "quentin halys" or n2.casefold() != "arthur fery"
                    or int(event.get("startTimestamp") or 0) != 1793700000
                    or str((event.get("status") or {}).get("type") or "") != "finished"
                    or int(event.get("winnerCode") or 0) != 1):
                raise ValueError("Halys/Fery identity, start, or final status mismatch")
            stats = parse_statistics(halys_stats, home_is_player1=True)
            aces1, aces2 = stats.get("p1_aces"), stats.get("p2_aces")
            if (aces1 != 17 or aces2 != 8):
                raise ValueError("Halys/Fery source-native ace counts differ from witness")
            value = {
                "status": "win", "provider_status": "finished ended",
                "winner_id": p1, "checked_at": checked_at,
                "provider_home_id": p1, "provider_away_id": p2,
                "projection_stats_p1_id": p1, "projection_stats_p2_id": p2,
                "projection_stats": {"p1_aces": int(aces1), "p2_aces": int(aces2)},
                "projection_stats_checked_at": checked_at,
            }
        else:
            value = statuses.get(event_id)
            if not isinstance(value, dict):
                raise ValueError("Historic provider-verified settlement missing: " + event_id)
            if (p1 != str(value.get("provider_home_id") or "")
                    or p2 != str(value.get("provider_away_id") or "")
                    or str(value.get("status") or "") not in {"win", "loss", "void"}):
                raise ValueError("Historic provider participant/status conflict: " + event_id)
            observation = str(value.get("checked_at") or "")
            when = datetime.fromisoformat(observation.replace("Z", "+00:00"))
            if (when.tzinfo is None or not observation.startswith(("2026-11-03", "2026-11-04"))):
                raise ValueError("Not a contemporaneous historic snapshot")
            if expected_aces is None:
                if (value["status"] != "void"
                        or "cancel" not in str(value.get("provider_status") or "").lower()):
                    raise ValueError("Unverified ACE cancellation")
            else:
                stats = value.get("projection_stats") or {}
                if (str(value.get("projection_stats_p1_id") or "") != p1
                        or str(value.get("projection_stats_p2_id") or "") != p2):
                    raise ValueError("Source-native player statistics identity mismatch")
                observed = stats.get("p1_aces" if selection == p1 else "p2_aces")
                if type(observed) not in (int, float) or observed != expected_aces:
                    raise ValueError("Unexpected actual ACE count: " + event_id)
        verified[event_id] = value
        # Only this exact original issued O/U contract is eligible. Never infer
        # a threshold from the model projection, match winner or opponent stats.
        publication_key = f"local-aces-ou-v1:{event_id}:{selection}:over:{line:.1f}"
        pub = {
            "section": "ace", "market": "aces", "selection_id": selection,
            "publication_key": publication_key,
            "publication_status": "published",
            "price_contract": "player_total_ou", "ou_side": "over",
            "market_line": line, "selection": f"{name} Over {line:.1f} Aces",
            "projection_scope": "player", "projection_metric": "aces",
            "projection": projection, "issued_at": ISSUED_AT,
            "odds": odds, "price_status": "priced_projection",
            "price_basis": "local_aces_statistical_v1",
            "source": "confirmed_telegram_ou_reissue",
        }
        players = [{"id": p1, "name": n1}, {"id": p2, "name": n2}]
        players[0 if selection == p1 else 1]["name"] = name
        category = (event.get("tournament") or {}).get("category") or {}
        tour = {3: "atp", 6: "wta"}.get(category.get("id"))
        if tour is None:
            raise ValueError("Unknown source-native tournament category")
        rows.append({
            "event_id": event_id, "scheduled_at": scheduled,
            "betting_day": DAY, "tour": tour,
            "player1": players[0], "player2": players[1],
            "selection_id": selection, "betting": {"selection_id": selection},
            "projection": projection, "market_publications": [pub],
        })
    feed = {"schema": 1, "generated_at": ISSUED_AT, "ace_picks": rows, "results": []}
    candidates = settled_archive_candidates(feed, verified)
    found = {str(r.get("event_id") or ""): r for r in candidates}
    if set(found) != {a[0] for a in ISSUED_ACES} or len(candidates) != 9:
        raise ValueError("Nine exact archived ACE contracts were not graded")
    for event_id, selection, _, _, line, _, odds, count in ISSUED_ACES:
        pub = found[event_id]["market_publications"][0]
        result = pub.get("result") or {}
        if (pub.get("publication_key") != f"local-aces-ou-v1:{event_id}:{selection}:over:{line:.1f}"
                or pub.get("odds") != odds
                or result.get("runtime_source") != "match_status_snapshot"
                or (result.get("void") is True) != (count is None)
                or (count is not None and (
                    result.get("actual_count") != count
                    or result.get("correct") is not (count > line)))):
            raise ValueError("Incorrect ACE settlement generated: " + event_id)
    return candidates


def _frozen_status_witness() -> dict:
    """Load exact provider-verified old-day evidence saved before 06:00 rollover."""
    proof = json.loads(
        Path(__file__).with_name("telegram_20261103_snapshot.json").read_text(encoding="utf-8")
    )
    expected = {entry[0] for entry in ISSUED_ACES if entry[0] != HALYS}
    if (proof.get("schema") != 1 or proof.get("betting_day") != DAY
            or proof.get("kind") != "historical_verified_match_status_snapshot"
            or proof.get("source_run_id") != 41775101814
            or proof.get("source_job_id") != 126393512626
            or proof.get("source_updated_at") != "2026-11-04T04:45:29.669788+00:00"
            or set(proof.get("statuses") or {}) != expected):
        raise RuntimeError("Historic source-native snapshot provenance mismatch")
    return {"statuses": proof["statuses"]}


def recover(*, dry_run: bool = True) -> dict:
    """Bounded API-Pro corroboration, protected archive write and independent readback."""
    snapshot = _frozen_status_witness()
    # PRECHECK: the 3 already settled TOP/VALUE selections must exist. FREE is
    # a duplicate of the lost TOP pick and does not change premium ROI.
    archive_before = load_settled_results_archive()
    must_exist = {("17476816", "399599"), ("17472515", "157808"),
                  ("17476833", "154572")}
    confirmed = set()
    for row in archive_before:
        for pub in row.get("market_publications") or []:
            result = pub.get("result") or {}
            key = (str(row.get("event_id") or ""), str(pub.get("selection_id") or ""))
            if key in must_exist and pub.get("market") == "match_winner" and (
                    type(result.get("correct")) is bool
                    and result.get("runtime_source") == "match_status_snapshot"):
                confirmed.add(key)
    if confirmed != must_exist:
        raise RuntimeError("Original TOP/VALUE archive does not have all 3 verified settlements")
    client = RapidTennisClient(settings, request_budget=lambda *a, **kw: reserve_shared_api_budget("match"))
    client.request_limit = 12
    client.retry_attempts = 1
    client.client.timeout = 5.0
    try:
        details = {
            event_id: client._get(f"/api/tennis/event/{event_id}", enrichment=True)
            for event_id, *_ in ISSUED_ACES
        }
        stats = client.event_statistics(HALYS)
    finally:
        client.close()
    now = datetime.now(timezone.utc).isoformat()
    candidates = _candidate_rows(snapshot, details, stats, now)
    before = {}
    targeted = {_identity(row, row["market_publications"][0]) for row in candidates}
    for row in archive_before:
        for pub in row.get("market_publications") or []:
            key = _identity(row, pub)
            if key not in targeted:
                continue
            if key in before:
                raise RuntimeError("Conflicting duplicate target archive identity")
            before[key] = row
    new_rows = []
    for row in candidates:
        pub = row["market_publications"][0]
        key = _identity(row, pub)
        current = before.get(key)
        if current is None:
            new_rows.append(row)
            continue
        prior = (current.get("market_publications") or [{}])[0].get("result") or {}
        result = pub["result"]
        if any(prior.get(field) != result.get(field)
               for field in ("runtime_source", "correct", "void", "actual_count")):
            raise RuntimeError("Conflicting pre-existing ACE settlement")
    planned = {
        "day": DAY, "provider_requests": client.request_count,
        "expected_ace_rows": 9, "existing_ace_rows": 9 - len(new_rows),
        "net_new_ace_rows": len(new_rows), "top_value_verified": len(confirmed),
        "mutation_permitted": not dry_run,
    }
    if dry_run:
        return {"status": "dry_run", **planned}
    if new_rows:
        written = save_settled_results_archive(new_rows)
        if not written.get("verified") or written.get("added") != len(new_rows) or written.get("updated"):
            raise RuntimeError("Expected append-only ACE archive readback failed")
    after = load_settled_results_archive()
    after_by_key = {
        _identity(row, pub): (row, pub)
        for row in after for pub in row.get("market_publications") or []
    }
    for row in candidates:
        pub = row["market_publications"][0]
        found = after_by_key.get(_identity(row, pub))
        if not found:
            raise RuntimeError("ACE settlement missing from independent readback")
        result = found[1].get("result") or {}
        original = pub["result"]
        if any(result.get(k) != original.get(k)
               for k in ("runtime_source", "correct", "void", "actual_count")):
            raise RuntimeError("ACE settlement readback changed grading")
    return {"status": "verified", **planned, "archived_ace_rows": 9}
