#!/usr/bin/env python3
"""Strict read-only dry-run of legacy previous-match scores into canonical BlinQ history."""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.errors import ProviderError
from tbt.match_format import exact_best_of_from_score_stats, explicit_best_of_from_event
from tbt.providers.score import parse_event_score

EXCLUDED_TOKENS = (
    "retir", "walkover", "walk over", "w/o", "cancel", "abandon",
    "interrupt", "suspend", "postpon",
)

SCORE_KEYS = (
    "p1_sets_won", "p2_sets_won", "p1_games_won", "p2_games_won",
    "p1_first_set_won", "p2_first_set_won", "total_sets", "total_games",
    "tiebreak_sets", "straight_sets", "deciding_set",
    "p1_set1_games", "p2_set1_games", "p1_set2_games", "p2_set2_games",
    "p1_second_set_won", "p2_second_set_won",
)


def _event_id(match: Any) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    values: list[Any] = []
    ident = payload.get("_tbt_event_identity")
    if isinstance(ident, dict):
        values.append(ident.get("event_id"))
    for key in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id"):
        values.append(payload.get(key))
    event = payload.get("event")
    if isinstance(event, dict):
        values.append(event.get("id"))
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def _team_id(event: dict[str, Any], side: str) -> str:
    team = event.get(side)
    if not isinstance(team, dict):
        return ""
    value = team.get("id")
    return "" if value in (None, "") else str(value)


def _status_text(event: dict[str, Any]) -> str:
    values: list[str] = []
    status = event.get("status")
    if isinstance(status, dict):
        for key in ("type", "name", "description", "reason"):
            if status.get(key) not in (None, ""):
                values.append(str(status.get(key)))
    elif status not in (None, ""):
        values.append(str(status))
    for key in ("reason", "endReason", "end_reason", "termination", "terminationReason"):
        if event.get(key) not in (None, ""):
            values.append(str(event.get(key)))
    return " | ".join(values).lower().replace("_", " ")


def _is_finished(event: dict[str, Any]) -> bool:
    status = event.get("status")
    if isinstance(status, dict):
        value = str(status.get("type") or status.get("name") or status.get("description") or "").lower()
    else:
        value = str(status or "").lower()
    return any(token in value for token in ("finished", "completed", "ended", "final", "ft"))


def _winner_from_event(event: dict[str, Any], home_id: str, away_id: str) -> str | None:
    code = event.get("winnerCode")
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code == 1:
        return home_id or None
    if code == 2:
        return away_id or None
    return None


def _coverage(matches: list[Any]) -> dict[str, int]:
    out = Counter()
    for match in matches:
        stats = match.stats if isinstance(match.stats, dict) else {}
        if stats.get("total_sets") is not None and stats.get("total_games") is not None:
            out["structured_score"] += 1
        if all(stats.get(k) is not None for k in (
            "p1_first_set_won", "p2_first_set_won",
            "p1_second_set_won", "p2_second_set_won",
        )):
            out["set1_set2_outcomes"] += 1
        if stats.get("deciding_set") is not None:
            out["deciding_set"] += 1
        if all(stats.get(k) is not None for k in (
            "p1_set1_games", "p2_set1_games", "p1_set2_games", "p2_set2_games",
        )):
            out["set1_set2_games"] += 1
    return dict(out)


def _write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--legacy-dir", default=".cache/tbt-pro")
    ap.add_argument("--out-dir", default=".cache/tbt/legacy-score-dryrun")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load_partitions(Path(args.history_dir))
    matches, safety = sanitize_history_identities(raw)
    by_event: dict[str, Any] = {}
    for match in matches:
        eid = _event_id(match)
        if eid:
            by_event[eid] = match

    before = _coverage(matches)

    prev_dir = Path(args.legacy_dir) / "blinq" / "data" / "form" / "previous_matches"
    files = sorted(prev_dir.glob("*.json"))
    counts = Counter()
    unique_events: dict[str, dict[str, Any]] = {}
    parse_errors = 0

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            parse_errors += 1
            continue
        events = doc.get("events") if isinstance(doc.get("events"), list) else []
        counts["raw_event_rows"] += len(events)
        for event in events:
            if not isinstance(event, dict):
                continue
            eid = str(event.get("id") or "")
            if not eid:
                counts["missing_event_id"] += 1
                continue
            home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
            away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
            filters = event.get("eventFilters") if isinstance(event.get("eventFilters"), dict) else {}
            category = filters.get("category")
            singles = (
                home.get("type") == 1 and away.get("type") == 1
                and (not isinstance(category, list) or "singles" in [str(x).lower() for x in category])
            )
            if not singles:
                counts["non_singles_excluded"] += 1
                continue
            if eid in unique_events:
                counts["duplicate_event_rows_collapsed"] += 1
                # Prefer the copy with more structured score periods.
                def depth(e: dict[str, Any]) -> int:
                    hs = e.get("homeScore") if isinstance(e.get("homeScore"), dict) else {}
                    return sum(hs.get(f"period{i}") is not None for i in range(1, 6))
                if depth(event) > depth(unique_events[eid]):
                    unique_events[eid] = event
            else:
                unique_events[eid] = event

    stage: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    projected_add = Counter()

    for eid, event in unique_events.items():
        counts["unique_singles_events"] += 1
        match = by_event.get(eid)
        if match is None:
            counts["unmatched_event_id"] += 1
            continue
        counts["canonical_event_linked"] += 1

        if not match.is_completed:
            counts["canonical_not_completed"] += 1
            continue
        if not _is_finished(event):
            counts["legacy_not_finished"] += 1
            continue
        status_text = _status_text(event)
        if any(token in status_text for token in EXCLUDED_TOKENS):
            counts["excluded_nonstandard_status"] += 1
            continue

        home_id = _team_id(event, "homeTeam")
        away_id = _team_id(event, "awayTeam")
        expected = {str(match.player1_id), str(match.player2_id)}
        observed = {home_id, away_id}
        if not home_id or home_id == away_id or observed != expected:
            counts["identity_mismatch"] += 1
            if len(rejections) < 200:
                rejections.append({
                    "event_id": eid, "reason": "identity_mismatch",
                    "expected_ids": sorted(expected), "observed_ids": sorted(observed),
                    "match_id": match.match_id,
                })
            continue
        counts["identity_verified"] += 1

        event_winner = _winner_from_event(event, home_id, away_id)
        if event_winner is not None and str(match.winner_id or "") != event_winner:
            counts["winner_mismatch"] += 1
            if len(rejections) < 200:
                rejections.append({
                    "event_id": eid, "reason": "winner_mismatch",
                    "canonical_winner": str(match.winner_id or ""),
                    "legacy_winner": event_winner,
                    "match_id": match.match_id,
                })
            continue

        home_is_p1 = home_id == str(match.player1_id)
        try:
            score = parse_event_score(event, home_is_player1=home_is_p1, best_of=None)
        except ProviderError as exc:
            counts["score_parser_rejected"] += 1
            if len(rejections) < 200:
                rejections.append({
                    "event_id": eid, "reason": "score_parser_rejected",
                    "detail": str(exc), "match_id": match.match_id,
                })
            continue
        if not score:
            counts["score_unavailable"] += 1
            continue

        score_best_of, score_source = exact_best_of_from_score_stats(score)
        if score_best_of not in {3, 5}:
            counts["score_format_unproven"] += 1
            continue
        provider_best_of = explicit_best_of_from_event(event)
        if provider_best_of in {3, 5} and provider_best_of != score_best_of:
            counts["provider_score_format_conflict"] += 1
            continue
        if match.best_of in {3, 5} and int(match.best_of) != score_best_of:
            counts["canonical_score_format_conflict"] += 1
            continue

        try:
            score = parse_event_score(event, home_is_player1=home_is_p1, best_of=score_best_of)
        except ProviderError as exc:
            counts["verified_score_reparse_rejected"] += 1
            if len(rejections) < 200:
                rejections.append({
                    "event_id": eid, "reason": "verified_score_reparse_rejected",
                    "detail": str(exc), "match_id": match.match_id,
                })
            continue

        existing = match.stats if isinstance(match.stats, dict) else {}
        conflicts = {}
        additions = {}
        for key, value in score.items():
            if key not in SCORE_KEYS:
                continue
            old = existing.get(key)
            if old is None:
                additions[key] = value
            else:
                try:
                    if abs(float(old) - float(value)) > 1e-9:
                        conflicts[key] = {"existing": old, "legacy": value}
                except Exception:
                    if old != value:
                        conflicts[key] = {"existing": old, "legacy": value}

        if conflicts:
            counts["stat_conflict_matches"] += 1
            if len(rejections) < 200:
                rejections.append({
                    "event_id": eid, "reason": "stat_conflict",
                    "match_id": match.match_id, "conflicts": conflicts,
                })
            continue
        if not additions:
            counts["already_complete_or_present"] += 1
            continue

        counts["stage_matches"] += 1
        for key in additions:
            counts[f"field_add_{key}"] += 1

        before_structured = existing.get("total_sets") is not None and existing.get("total_games") is not None
        after_stats = {**existing, **additions}
        after_structured = after_stats.get("total_sets") is not None and after_stats.get("total_games") is not None
        if not before_structured and after_structured:
            projected_add["structured_score"] += 1

        before_set12 = all(existing.get(k) is not None for k in (
            "p1_first_set_won", "p2_first_set_won", "p1_second_set_won", "p2_second_set_won"
        ))
        after_set12 = all(after_stats.get(k) is not None for k in (
            "p1_first_set_won", "p2_first_set_won", "p1_second_set_won", "p2_second_set_won"
        ))
        if not before_set12 and after_set12:
            projected_add["set1_set2_outcomes"] += 1
        if existing.get("deciding_set") is None and after_stats.get("deciding_set") is not None:
            projected_add["deciding_set"] += 1

        stage.append({
            "schema": 1,
            "match_id": match.match_id,
            "provider_event_id": eid,
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc).isoformat(),
            "player1_id": str(match.player1_id),
            "player2_id": str(match.player2_id),
            "player1_name": match.player1_name,
            "player2_name": match.player2_name,
            "best_of": score_best_of,
            "best_of_source": score_source,
            "additions": additions,
            "identity_verified": True,
            "winner_verified": event_winner is None or event_winner == str(match.winner_id or ""),
            "source_repository": "BackstageTalks/tbt-pro",
            "source_family": "API_PRO_PREVIOUS_MATCHES_CACHE",
        })

    projected_after = dict(before)
    for key, value in projected_add.items():
        projected_after[key] = int(projected_after.get(key, 0)) + int(value)

    report = {
        "schema": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "zero_provider_api_requests": True,
        "canonical_rows": len(matches),
        "identity_safety": safety,
        "legacy_cache_files": len(files),
        "parse_errors": parse_errors,
        "counts": dict(counts),
        "stage_rows": len(stage),
        "coverage_before": before,
        "coverage_projected_add": dict(projected_add),
        "coverage_projected_after": projected_after,
        "policy": {
            "link": "exact provider event_id only",
            "identity": "exact home/away provider player IDs must equal canonical player IDs",
            "winner": "legacy winnerCode must agree with canonical winner when present",
            "score": "same strict tbt.providers.score.parse_event_score parser as production",
            "format": "structured score must prove BO3/BO5; provider/canonical conflicts fail closed",
            "write": "dry-run only; no canonical history mutation",
        },
    }
    _write_jsonl_gz(out_dir / "stage.jsonl.gz", stage)
    _write_jsonl_gz(out_dir / "rejections_sample.jsonl.gz", rejections)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
