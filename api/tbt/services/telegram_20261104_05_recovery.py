"""One-time 4–5 Nov exact ACE Results append from already archived player counts.

No source/API request, CDB write or Telegram send. All 12 original records were
confirmed before match start by private Telegram ledger and 2026-11-07 read-only
archive audit 42353354060. Normal Results CAS performs all writes/readbacks.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from tbt.services.results_archive import (
    _archive_record, _identity, load_settled_results_archive, save_settled_results_archive,
)
from tbt.services.telegram_20261106_recovery import _verified_count_evidence

ISSUED = {
    "2026-11-04": {
        "sent_at": "2026-11-04T05:38:38.877232+00:00",
        "message_ids": [732, 733], "sent_rows": 16,
        "premium_counts": {"won": 8, "lost": 7, "void": 0, "pending": 0},
        # Already archived sixth original ACE publication is left untouched.
        "ace": (
            ("17483450","315575","Karim Ibrahim","10:00",5.5,7.21,1.67,9),
            ("17428228","136042","Taylor Fritz","13:50",8.5,10.31,1.73,37),
            ("17428207","90798","Quentin Halys","10:00",11.5,12.95,1.60,17),
            ("17488695","273778","Alec Deckers","20:00",6.5,7.71,1.61,6),
            ("17486949","373228","Eric David Verdes","17:00",3.5,4.88,1.75,3),
        ),
    },
    "2026-11-05": {
        "sent_at": "2026-11-05T09:11:27.931790+00:00",
        "message_ids": [734, 735], "sent_rows": 13,
        "premium_counts": {"won": 9, "lost": 3, "void": 0, "pending": 0},
        "ace": (
            ("17427366","289146","Giovanni Mpetshi Perricard","16:00",11.5,13.46,1.73,13),
            ("17427631","107357","Hugo Grenier","10:40",4.5,5.58,1.65,1),
            ("17428222","90798","Quentin Halys","10:00",9.5,11.32,1.62,16),
            ("17427362","229218","Otto Virtanen","12:10",6.5,8.26,1.61,9),
            ("17427548","161262","Thiago Seyboth Wild","22:00",3.5,4.9,1.77,2),
            ("17427589","289106","Coleman Wong","10:30",6.5,8.47,1.78,12),
            ("17428229","136042","Taylor Fritz","19:30",8.5,10.29,1.75,14),
        ),
    },
}


def exact_candidates(archive: list[dict], day: str) -> list[dict]:
    if day not in ISSUED:
        raise ValueError("Recovery day is not approved")
    manifest = ISSUED[day]
    from tbt.services.telegram_20261106_recovery import _utc
    issued = _utc(manifest["sent_at"])
    if len({e for e, *_ in manifest["ace"]}) != len(manifest["ace"]):
        raise ValueError("Frozen recovery event duplicate")
    rows = []
    for eid, pid, name, clock, line, projection, odds, actual in manifest["ace"]:
        scheduled = f"{day}T{clock}:00+00:00"
        if not (issued < _utc(scheduled) and 1.60 <= odds <= 1.80):
            raise ValueError("Original publication time/price invalid")
        if type(actual) is not int or actual < 0 or line < 0:
            raise ValueError("Invalid provider count or local O/U line")
        witness = _verified_count_evidence(archive, eid, pid, scheduled, actual)
        source_row, source_result = witness["row"], witness["result"]
        outcome = actual > line
        if actual == line:  # Actual integer and frozen half-ace line preclude PUSH.
            raise ValueError("Unexpected ACE tie")
        publication = {
            "section": "ace", "market": "aces", "selection_id": pid,
            "publication_key": f"local-aces-ou-v1:{eid}:{pid}:over:{line:.1f}",
            "publication_status": "published", "price_contract": "player_total_ou",
            "ou_side": "over", "market_line": line,
            "selection": f"{name} Over {line:.1f} Aces",
            "projection_scope": "player", "projection_metric": "aces",
            "projection": projection, "issued_at": manifest["sent_at"],
            "odds": odds, "price_status": "priced_projection",
            "price_basis": "local_aces_statistical_v1",
            "source": "confirmed_telegram_ou_reissue",
            "result": {
                "status": "hit" if outcome else "miss",
                "correct": outcome, "void": False,
                "actual_count": actual,
                "scheduled_at": scheduled,
                "settled_at": source_result.get("settled_at"),
                "runtime_overlay": True,
                "runtime_source": "match_status_snapshot",
                "recovery_evidence": "existing_verified_exact_player_aces_count_v1",
                "projection_scope": "player",
                "projection_metric": "aces", "projection": projection,
                "staked_units": 1.0,
                "return_units": odds if outcome else 0.0,
                "profit_units": round(odds-1.0 if outcome else -1.0, 8),
            },
        }
        record = {
            k: deepcopy(source_row[k])
            for k in ("event_id","scheduled_at","betting_day","tour","tournament",
                      "tournament_id","round","surface")
            if k in source_row
        }
        record.update(
            event_id=eid, scheduled_at=scheduled, betting_day=day,
            player1=deepcopy(source_row["player1"]),
            player2=deepcopy(source_row["player2"]),
            market_publications=[publication],
        )
        native = _archive_record(record, publication, manifest["sent_at"])
        if native is None:
            raise ValueError("Native Results archive rejected original frozen ACE")
        rows.append(native)
    return rows


def recover(day: str, *, dry_run: bool = True) -> dict:
    """CAS append only absent exact contracts. Safe retry and full readback."""
    if day not in ISSUED:
        raise ValueError("Unsupported historical recovery day")
    before = load_settled_results_archive()
    candidates = exact_candidates(before, day)
    expected = {_identity(row, row["market_publications"][0]): row for row in candidates}
    if not all(expected) or len(expected) != len(candidates):
        raise RuntimeError("Duplicate or missing original market identities")
    existing = {}
    for row in before:
        for pub in row.get("market_publications") or []:
            key = _identity(row, pub)
            if key in expected:
                existing.setdefault(key, []).append(row)
    pending = []
    for key, candidate in expected.items():
        prior = existing.get(key) or []
        if len(prior) > 1:
            raise RuntimeError("Ambiguous original archived publication")
        if not prior:
            pending.append(candidate)
            continue
        if prior[0] != candidate:
            raise RuntimeError("Existing exact original publication differs; no overwrite")
    result = {
        "day": day, "status": "dry_run" if dry_run else "commit_pending",
        "original_telegram_message_ids": ISSUED[day]["message_ids"],
        "original_sent_rows": ISSUED[day]["sent_rows"],
        "verified_actual_player_counts": len(candidates),
        "already_archived": len(candidates)-len(pending),
        "net_new": len(pending),
        "provider_requests": 0, "cdb_writes": 0,
        "telegram_sent": False, "archive_updated": 0,
    }
    if dry_run:
        return result
    if pending:
        write = save_settled_results_archive(pending)
        if (write.get("verified") is not True or write.get("added") != len(pending)
                or write.get("updated") != 0):
            raise RuntimeError("Native Results CAS append/readback failed")
    after = load_settled_results_archive()
    actual = {}
    for row in after:
        for pub in row.get("market_publications") or []:
            key = _identity(row, pub)
            if key in expected:
                actual.setdefault(key, []).append(row)
    if set(actual) != set(expected) or any(
        len(actual[k]) != 1 or actual[k][0] != row for k, row in expected.items()
    ):
        raise RuntimeError("Independent original-ACE Results readback mismatch")
    return {**result, "status": "verified",
            "archived_exact_original_aces": len(actual)}


def preflight(days: tuple[str, ...] = ("2026-11-04", "2026-11-05")) -> list[dict]:
    """No mutation; both days must be verified before a commit dispatch."""
    if len(days) != len(set(days)) or not days:
        raise ValueError("Invalid day list")
    return [recover(day, dry_run=True) for day in days]
