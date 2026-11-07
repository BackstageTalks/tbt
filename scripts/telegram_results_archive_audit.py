"""Read-only Telegram issued-vs-archive audit. No API provider calls or writes."""
from __future__ import annotations
import json
import math
from collections import Counter
from pathlib import Path

import telegram_daily_results as results
import telegram_offer_publisher as tg

DAYS = ("2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06")
FIELDS = ("event_id", "selection_id", "section", "market",
          "publication_key", "market_line", "projection_direction")


def mismatch_reason(sent: dict, archive_rows: list[dict]) -> dict:
    """Diagnose exact-source mismatch without grading or relaxing identity."""
    matches = [
        r for r in archive_rows if isinstance(r, dict)
        and str(r.get("event_id") or "") == str(sent.get("event_id") or "")
    ]
    if not matches:
        return {"reason": "no_verified_archive_event", "candidates": 0}
    for field in FIELDS[1:]:
        matches = [
            r for r in matches
            if str(r.get(field) or "") == str(sent.get(field) or "")
        ]
        if not matches:
            return {"reason": field + "_mismatch", "candidates": 0}
    return {"reason": "exact_identity_non_final_or_ambiguous",
            "candidates": len(matches)}



def verified_aces_actual_evidence(sent: dict, archive_rows: list[dict]) -> dict:
    """Check reusable, exact-player provider counts; NEVER grade or write.

    An alternate O/U threshold may have been graded for the same player.
    That is NOT proof that the sent threshold was settled, but its actual
    provider-verified player count may be reusable after an independent
    original-contract check. Reject other players, stale fixtures, missing
    count, invalid provenance and disagreeing measurements.
    """
    if sent.get("market") != "aces" or sent.get("section") != "ace":
        return {"status": "not_player_aces"}
    event = str(sent.get("event_id") or "")
    player = str(sent.get("selection_id") or "")
    day_time = str(sent.get("scheduled_at") or "")
    if not (event and player and day_time):
        return {"status": "missing_frozen_identity"}
    counts = []
    for row in archive_rows:
        if not isinstance(row, dict) or any(
            str(row.get(key) or "") != expected
            for key, expected in (
                ("event_id", event), ("selection_id", player),
                ("section", "ace"), ("market", "aces"),
                ("scheduled_at", day_time),
            )
        ):
            continue
        result = row.get("result")
        if not isinstance(result, dict) or result.get("runtime_source") != "match_status_snapshot":
            continue
        raw = result.get("actual_count")
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            actual = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(actual) or actual < 0 or not actual.is_integer():
            continue
        if type(result.get("correct")) is not bool and result.get("void") is not True:
            continue
        counts.append(int(actual))
    if not counts:
        return {"status": "no_verified_player_count", "sources": 0}
    if len(set(counts)) != 1:
        return {"status": "conflicting_player_counts", "sources": len(counts)}
    return {"status": "unique_verified_player_count",
            "actual_count": counts[0], "sources": len(counts)}


def audit(state: dict, url: str, days: tuple[str, ...] = DAYS) -> list[dict]:
    summaries = []
    for day in days:
        sent = results.extract_sent(state, day)
        archived = results.archive(url, day) if sent else []
        unresolved = []
        counts = Counter()
        for row in sent:
            outcome = results.evaluate(row, archived)
            counts[outcome["status"]] += 1
            if outcome["status"] != "pending":
                continue
            problem = mismatch_reason(row, archived)
            unresolved.append({
                "event_id": row.get("event_id"),
                "selection_id": row.get("selection_id"),
                "channel": row.get("channel"),
                "market": row.get("market"),
                "publication_key": row.get("publication_key"),
                "reason": problem["reason"],
                "candidate_count": problem["candidates"],
                "ace_actual_evidence": verified_aces_actual_evidence(row, archived),
            })
        summary = {
            "day": day,
            "sent_references": len(sent),
            "archive_rows": len(archived),
            "pending_aces_with_verified_count": sum(
                item["ace_actual_evidence"]["status"] == "unique_verified_player_count"
                for item in unresolved
            ),
            "verified": counts["won"] + counts["lost"] + counts["void"],
            "pending": counts["pending"],
            "by_status": dict(counts),
            "already_sent": (state.get("attempts") or {}).get("results:" + day, {}).get("status") == "sent",
            "unresolved": unresolved,
        }
        summaries.append(summary)
        print("RESULTS_ARCHIVE_AUDIT " + json.dumps(summary, sort_keys=True), flush=True)
    return summaries


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    request = json.loads(
        Path(".github/telegram-results-archive-audit-request.json").read_text("utf-8")
    )
    assert request == {
        "schema": 1, "days": list(DAYS), "mode": "read-only",
        "paid_provider_requests": 0, "telegram_send": False, "cdb_writes": False,
        "diagnostics": "verified_same_player_aces_count_v1",
    }, "Unexpected results audit authorization"
    state = tg.load(args.state)
    assert isinstance(state, dict) and isinstance(state.get("attempts"), dict)
    audit(state, args.url)
