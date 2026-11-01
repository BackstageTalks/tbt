"""Read-only CDB-facing normalization of immutable MoviOdds final-source archives.

This is NOT a canonical linker or CDB writer. Exact CDB match IDs, canonical
player1/player2 orientation, and import_ready may only be assigned later by
the approved identity/score matcher against the authoritative CDB.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any

ARCHIVE_SCHEMA = 2
ARCHIVE_FORMAT = "blinq.moviodds.tennis-final.cdb-source.v1"
_SOURCE_ID = re.compile(r"^[0-9]{3,20}$")
_DOUBLES = re.compile(r"(?:^|[\s(])(?:MD|WD|XD|DOUBLES)(?:$|[\s)])", re.IGNORECASE)


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(payload: dict) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _is_utc(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except (TypeError, ValueError):
        return False


def _counts(raw_side: dict) -> dict:
    output = {}
    for name in ("aces", "double_faults"):
        value = raw_side.get(name)
        if value is None:
            output[name] = None
        elif (isinstance(value, bool) or not isinstance(value, (int, float))
              or not math.isfinite(value) or int(value) != value
              or not 0 <= value <= 250):
            raise ValueError("Invalid MoviOdds count field")
        else:
            output[name] = int(value)
    return output


def _percentages(raw_side: dict) -> dict:
    output = {}
    for name in ("first_serve_win_pct", "break_point_conversion_pct"):
        value = raw_side.get(name)
        if value is None:
            output[name] = None
        elif (isinstance(value, bool) or not isinstance(value, (int, float))
              or not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError("Invalid source-native percentage")
        else:
            output[name] = float(value)
    return output


def _tour(league: str) -> str | None:
    # Do NOT classify UTR/ITF/Challenger as a canonical ATP/WTA event.
    league = league.strip().upper()
    if league.startswith("ATP "):
        return "atp"
    if league.startswith("WTA "):
        return "wta"
    return None


def _candidate(payload: dict, source_sha256: str) -> dict:
    fixture = str(payload.get("fixture_id") or "")
    if not _SOURCE_ID.fullmatch(fixture):
        raise ValueError("Missing/invalid provider fixture identity")
    if payload.get("source") != "moviodds" or payload.get("status") != "finished":
        raise ValueError("Nonfinal MoviOdds payload in CDB archive")
    home, away = str(payload.get("home") or "").strip(), str(payload.get("away") or "").strip()
    if not home or not away or home.casefold() == away.casefold():
        raise ValueError("Ambiguous source participant names")
    score = str(payload.get("final_score") or "").strip()
    finished = str(payload.get("finished_at") or "")
    if not score or not _is_utc(finished):
        raise ValueError("Missing final-score or finished-at evidence")
    stats = payload.get("stats")
    if not isinstance(stats, dict) or stats.get("sport") != "tennis":
        raise ValueError("Missing provider-native tennis stats")
    sides = (stats.get("home"), stats.get("away"))
    if any(not isinstance(side, dict) for side in sides):
        raise ValueError("Missing home/away stat sides")
    league = str(payload.get("league") or "")
    is_doubles = ("/" in home or "/" in away or _DOUBLES.search(league) is not None)
    tour = _tour(league)
    kickoff = str(payload.get("kickoff_utc") or "").strip()
    if kickoff and not _is_utc(kickoff):
        raise ValueError("Invalid provider kickoff time")
    observed = str(payload.get("observed_at") or "")
    if not _is_utc(observed):
        raise ValueError("Missing provenance observation timestamp")
    expected_sha = _digest(payload)
    if source_sha256 != expected_sha:
        raise ValueError("Source record checksum mismatch")

    blocked = ["canonical_identity_not_linked", "final_score_not_independently_verified"]
    if is_doubles:
        blocked.append("doubles_not_in_scope")
    if tour is None:
        blocked.append("canonical_tour_unconfirmed")
    if not kickoff:
        blocked.append("kickoff_utc_missing")
    if not any(_counts(side)[name] is not None
               for side in sides for name in ("aces", "double_faults")):
        blocked.append("no_usable_count_values")

    return {
        "schema": 1,
        "source": "moviodds",
        "source_fixture_id": fixture,
        "source_sha256": source_sha256,
        "provenance": {
            "provider": "moviodds",
            "record_sha256": source_sha256,
            "source_updated_at_utc": observed,
            "source_finalized_at_utc": finished,
            "sample_type": "finished_result",
            "source_final_score": score,
            "source_match_stats": "provider_native",
        },
        "match": {
            "home_name": home, "away_name": away,
            "league": league,
            "tour_hint": tour,
            "event_type": "doubles" if is_doubles else "singles_unconfirmed",
            "scheduled_at_utc": kickoff or None,
            "finished_at_utc": finished,
            "final_score_source": score,
            "set_scores_source": payload.get("periods") or [],
            "surface_source": str(stats.get("surface") or "") or None,
            "best_of_source": str(stats.get("format") or "") or None,
            "round_source": None,
        },
        # Source-side orientation MUST be resolved against CDB's p1/p2
        # after unique ID + score matching. These aren't import-ready CDB cells.
        "source_side_counts": {
            "home": _counts(sides[0]), "away": _counts(sides[1]),
        },
        # Percentages stay 0..100. Never coerce them into a CDB 0..1 ratio
        # without verifying definitions, denominators and quality precedence.
        "unmapped_source_percentages": {
            "home": _percentages(sides[0]), "away": _percentages(sides[1]),
        },
        "cdb_link": {
            "status": "unlinked",
            "match_id": None,
            "canonical_player1_id": None,
            "canonical_player2_id": None,
            "canonical_signature": None,
            "incoming_stats": None,
            "import_ready": False,
            "review_reasons": blocked,
        },
    }


def format_cdb_archive(export: dict) -> dict:
    """Preserve original verified payloads, add one typed candidate per row.

    Output is stable and idempotent: raw payload SHA is unchanged; filename SHA
    changes only when the data or the normalized schema changes.
    """
    if not isinstance(export, dict) or export.get("schema") != 1:
        raise ValueError("Unexpected MoviOdds provider export schema")
    if export.get("verified") is not True or export.get("source") != "moviodds":
        raise ValueError("MoviOdds source export was not independently verified")
    days = export.get("days")
    if not isinstance(days, list) or len(days) != 1 or not isinstance(days[0], str):
        raise ValueError("CDB archive expects one UTC day")
    date.fromisoformat(days[0])
    records = export.get("records")
    if not isinstance(records, list) or export.get("count") != len(records):
        raise ValueError("Source export record count mismatch")

    output = []
    seen = set()
    stats = {"raw": len(records), "unlinked": 0, "source_atp_wta_singles": 0,
             "doubles_excluded": 0, "other_tour_review": 0,
             "with_aces": 0, "with_double_faults": 0, "cdb_imported": 0}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            raise ValueError("Malformed MoviOdds export row")
        raw, sha = record["payload"], record.get("sha256")
        if str(raw.get("finished_at") or "")[:10] != days[0]:
            raise ValueError("Cross-day source payload")
        candidate = _candidate(raw, sha)
        key = candidate["source_fixture_id"]
        if key in seen:
            raise ValueError("Duplicate provider fixture in archive")
        seen.add(key)
        source_counts = candidate["source_side_counts"]
        stats["unlinked"] += 1
        if any(side.get("aces") is not None for side in source_counts.values()):
            stats["with_aces"] += 1
        if any(side.get("double_faults") is not None for side in source_counts.values()):
            stats["with_double_faults"] += 1
        match = candidate["match"]
        if match["event_type"] == "doubles":
            stats["doubles_excluded"] += 1
        elif match["tour_hint"] in ("atp", "wta"):
            stats["source_atp_wta_singles"] += 1
        else:
            stats["other_tour_review"] += 1
        # Original raw payload and its exact digest are kept untouched.
        output.append({"payload": raw, "sha256": sha, "cdb_candidate": candidate})

    return {
        "schema": ARCHIVE_SCHEMA,
        "format": ARCHIVE_FORMAT,
        "source": "moviodds",
        "source_export_schema": 1,
        "source_verified": True,
        "days": days,
        "count": len(output),
        "records": output,
        "cdb_import_ready": False,
        "cdb_write_performed": False,
        "summary": stats,
    }


def verify_cdb_archive(archive: dict) -> None:
    """Independent readback validation of normalized fields against raw data."""
    if not isinstance(archive, dict) or archive.get("format") != ARCHIVE_FORMAT:
        raise ValueError("Unknown MoviOdds CDB archive format")
    baseline = {
        "schema": 1, "source": "moviodds", "verified": True,
        "days": archive.get("days"), "count": archive.get("count"),
        "records": [{"payload": r["payload"], "sha256": r["sha256"]}
                    for r in archive.get("records", [])],
    }
    expected = format_cdb_archive(baseline)
    if archive != expected:
        raise ValueError("CDB-normalized archive changed or does not match source")
