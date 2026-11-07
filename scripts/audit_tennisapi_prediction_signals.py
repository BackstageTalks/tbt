"""Fail-closed, offline TennisApi tournament signal reconciliation.

No provider calls, canonical writes, model changes or import authority.
Use source-native event IDs ONLY for exact read-only reconciliation; BlinQ
canonical match_id is deliberately NOT the provider event ID.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

ALLOWED_TOURS = {"atp", "wta"}
MAX_SOURCE_EVENTS = 200_000
MAX_SOURCE_BYTES = 32 * 1024 * 1024


def _positive(value: Any) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _seed(value: Any) -> int | None:
    if type(value) is int and 1 <= value <= 128:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
        return parsed if 1 <= parsed <= 128 else None
    return None


def _duration_seconds(event: dict) -> int | None:
    """Recorded *finished* set durations only. Other time fields are not duration."""
    periods = event.get("time")
    if not isinstance(periods, dict):
        return None
    seconds = [periods.get(f"period{i}") for i in range(1, 6)]
    measured = [n for n in seconds if type(n) is int and 0 < n <= 8 * 3600]
    if not measured or any(n is not None and n not in measured for n in seconds):
        return None
    total = sum(measured)
    return total if 300 <= total <= 12 * 3600 else None


def source_event(event: Any) -> tuple[dict | None, str]:
    """Validate usable ATP/WTA singles history; never assume unknown discipline."""
    if not isinstance(event, dict):
        return None, "not_object"
    eid, stamp = _positive(event.get("id")), _positive(event.get("startTimestamp"))
    if eid is None or stamp is None:
        return None, "invalid_id_or_time"
    try:
        when = datetime.fromtimestamp(stamp, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, "invalid_timestamp"
    tournament = event.get("tournament")
    if not isinstance(tournament, dict):
        return None, "missing_tournament"
    category = tournament.get("category")
    tour = category.get("slug") if isinstance(category, dict) else None
    if tour not in ALLOWED_TOURS:
        return None, "out_of_scope_tour"
    unique = tournament.get("uniqueTournament")
    uid = _positive(unique.get("id")) if isinstance(unique, dict) else None
    if uid is None:
        return None, "missing_native_tournament"
    sides = (event.get("homeTeam"), event.get("awayTeam"))
    if any(not isinstance(side, dict) or type(side.get("type")) is not int
           or side.get("type") != 1 for side in sides):
        return None, "discipline_unconfirmed_or_doubles"
    ids = tuple(_positive(side.get("id")) for side in sides)
    if ids[0] is None or ids[1] is None or ids[0] == ids[1]:
        return None, "invalid_players"
    status = event.get("status")
    if not isinstance(status, dict) or status.get("type") != "finished":
        return None, "not_finished"
    winner = event.get("winnerCode")
    if type(winner) is not int or winner not in (1, 2):
        return None, "missing_winner"
    home, away = event.get("homeScore"), event.get("awayScore")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None, "missing_score"
    hsets, asets = home.get("current"), away.get("current")
    if (type(hsets) is not int or type(asets) is not int
            or hsets == asets or (hsets > asets) != (winner == 1)):
        return None, "winner_score_conflict"
    home_seed, away_seed = _seed(event.get("homeTeamSeed")), _seed(event.get("awayTeamSeed"))
    roundinfo = event.get("roundInfo")
    round_name = roundinfo.get("name") if isinstance(roundinfo, dict) else None
    season = event.get("season")
    season_id = _positive(season.get("id")) if isinstance(season, dict) else None
    return {
        "event_id": eid, "utc_day": when.date().isoformat(), "timestamp": stamp,
        "tour": tour, "unique_tournament_id": uid, "season_id": season_id,
        "home_id": ids[0], "away_id": ids[1], "winner_id": ids[winner - 1],
        "round": str(round_name or ""), "home_seed": home_seed,
        "away_seed": away_seed, "duration_seconds": _duration_seconds(event),
        "source_prematch_seed_temporal_attestation": False,
        "source_duration_is_postmatch": True,
    }, "eligible_source_row"


def _identity(row: dict) -> tuple:
    return (row["event_id"], row["utc_day"], row["tour"],
            row["unique_tournament_id"], row["home_id"], row["away_id"],
            row["winner_id"])


def load_samples(paths: list[Path]) -> tuple[list[dict], dict]:
    if not paths:
        raise ValueError("At least one raw provider sample is required")
    observed: dict[int, dict] = {}
    removed: set[int] = set()
    counts: Counter = Counter()
    digests: list[dict] = []
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Unsafe or oversized source file")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw.decode("utf-8"))
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list) or len(events) > MAX_SOURCE_EVENTS:
            raise ValueError("Expected bounded events array")
        counts["raw"] += len(events)
        digests.append({"sha256": digest, "raw_rows": len(events)})
        for event in events:
            row, reason = source_event(event)
            counts[reason] += 1
            if row is None:
                continue
            eid = row["event_id"]
            if eid in removed:
                continue
            prior = observed.get(eid)
            if prior is None:
                observed[eid] = row
            elif prior != row:
                # Conflicting records with the same native ID are never merged.
                del observed[eid]
                removed.add(eid)
                counts["quarantine_conflicting_native_id"] += 1
            else:
                counts["duplicate_identical_source_event"] += 1
    counts["eligible_unique"] = len(observed)
    counts["quarantined_native_ids"] = len(removed)
    return sorted(observed.values(), key=lambda x: (x["utc_day"], x["event_id"])), {
        "counts": dict(sorted(counts.items())), "sources": digests,
    }


def pre_match_signals(rows: list[dict]) -> list[dict]:
    """Snapshot all matches on one UTC day BEFORE updating prior days.

    A prior match's duration can only inform strictly later UTC dates.
    Missing duration coverage is NOT the same as a verified zero workload.
    """
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[row["utc_day"]].append(row)
    prior: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    out = []
    for day in sorted(by_day):
        day_start = datetime.fromisoformat(day).date()
        staged: list[dict] = []
        for row in by_day[day]:
            players = (row["home_id"], row["away_id"])
            windows = []
            for player in players:
                past = [(d, duration) for d, duration in prior[(row["tour"], player)]
                        if (day_start - datetime.fromisoformat(d).date()).days in range(1, 8)]
                windows.append(sum(duration for _, duration in past) if past else None)
            home_seed, away_seed = row["home_seed"], row["away_seed"]
            both_seeded = home_seed is not None and away_seed is not None
            both_workload = all(value is not None for value in windows)
            out.append({
                **row,
                "seed_advantage_home": (away_seed - home_seed) if both_seeded else None,
                "seed_known_both": both_seeded,
                "recorded_duration_7d_home_seconds": windows[0],
                "recorded_duration_7d_away_seconds": windows[1],
                "duration_7d_advantage_home_seconds": (
                    windows[1] - windows[0] if both_workload else None),
                "duration_7d_known_both": both_workload,
                "historical_duration_window_complete": False,
                "point_in_time_day_snapshotted": True,
                "eligible_for_model_training": False,
            })
            if row["duration_seconds"] is not None:
                staged.append(row)
        for row in staged:
            for pid in (row["home_id"], row["away_id"]):
                prior[(row["tour"], pid)].append((day, row["duration_seconds"]))
    return out


def reconcile(rows: list[dict], history: list[Any] | None) -> dict:
    """Strict event-ID + day + native player-pair + tour read-only check."""
    summary = Counter()
    if history is None:
        for row in rows:
            row["canonical_link_status"] = "not_checked"
            row["canonical_match_id"] = None
        return {"status": "NOT_CHECKED", "linked": None, "potential_unlinked": None,
                "conflicts": None, "persisted_new_values": 0}
    by_id: dict[int, list[Any]] = defaultdict(list)
    for match in history:
        native = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        eid = _positive(native.get("id"))
        if eid is not None:
            by_id[eid].append(match)
    for row in rows:
        matches = by_id.get(row["event_id"], [])
        if len(matches) != 1:
            status = "potential_unlinked" if not matches else "ambiguous_canonical_event_id"
        else:
            match = matches[0]
            try:
                played_day = match.scheduled_at.astimezone(timezone.utc).date().isoformat()
                equal = (
                    played_day == row["utc_day"] and match.tour == row["tour"]
                    and {str(match.player1_id), str(match.player2_id)}
                    == {str(row["home_id"]), str(row["away_id"])}
                )
            except (AttributeError, TypeError, ValueError):
                equal = False
            status = "linked" if equal else "identity_conflict"
        row["canonical_link_status"] = status
        row["canonical_match_id"] = matches[0].match_id if status == "linked" else None
        summary[status] += 1
    return {
        "status": "READ_ONLY_RECONCILED", "linked": summary["linked"],
        "potential_unlinked": summary["potential_unlinked"],
        "conflicts": summary["identity_conflict"] + summary["ambiguous_canonical_event_id"],
        "persisted_new_values": 0,
    }



def check_monthly_tournaments(rows: list[dict], calendar_path: Path | None) -> dict:
    """Optional index cross-check only: calendar days are never import completeness."""
    if calendar_path is None:
        return {"status": "NOT_CHECKED", "verified_complete_days": 0}
    if (calendar_path.is_symlink() or not calendar_path.is_file()
            or calendar_path.stat().st_size > MAX_SOURCE_BYTES):
        raise ValueError("Unsafe or oversized calendar file")
    payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    dates = payload.get("dailyUniqueTournaments") if isinstance(payload, dict) else None
    if not isinstance(dates, list) or len(dates) > 31:
        raise ValueError("Invalid provider monthly calendar envelope")
    seen: dict[str, set[int]] = {}
    for item in dates:
        if not isinstance(item, dict):
            raise ValueError("Invalid monthly index row")
        day, ids = item.get("date"), item.get("uniqueTournamentIds")
        try:
            dt = datetime.fromisoformat(day).date()
        except (ValueError, TypeError):
            raise ValueError("Invalid monthly day") from None
        if day != dt.isoformat() or day in seen or not isinstance(ids, list):
            raise ValueError("Duplicate or malformed monthly day")
        if any(_positive(x) is None for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("Ambiguous tournament IDs for day")
        seen[day] = set(ids)
    if len({day[:7] for day in seen}) > 1:
        raise ValueError("Expected one exact calendar month")
    matched = missing = outside = 0
    for row in rows:
        day = row["utc_day"]
        if day not in seen:
            outside += 1
        elif row["unique_tournament_id"] in seen[day]:
            matched += 1
        else:
            missing += 1
    return {
        "status": "READ_ONLY_MONTHLY_INDEX",
        "index_days": len(seen),
        "unique_tournament_ids": len(set().union(*seen.values())) if seen else 0,
        "index_tournament_day_links": sum(map(len, seen.values())),
        "matched_source_events": matched,
        "missing_tournament_in_index": missing,
        "source_events_outside_index_days": outside,
        "verified_complete_days": 0,
        "skip_daily_category_import": False,
    }

def audit(paths: list[Path], *, history: list[Any] | None = None,
          calendar: Path | None = None) -> tuple[list[dict], dict]:
    source_rows, inventory = load_samples(paths)
    signals = pre_match_signals(source_rows)
    reconciliation = reconcile(signals, history)
    counts = Counter()
    for row in signals:
        counts["seed_known_both"] += bool(row["seed_known_both"])
        counts["any_seed"] += row["home_seed"] is not None or row["away_seed"] is not None
        counts["observed_duration"] += row["duration_seconds"] is not None
        counts["duration_7d_known_both"] += bool(row["duration_7d_known_both"])
    report = {
        "schema": 1,
        "scope": "read_only_research",
        "provider_requests": 0, "cdb_writes": 0, "model_changes": 0,
        "history_scope": "ATP_WTA_finished_singles",
        "source": inventory,
        "monthly_index": check_monthly_tournaments(signals, calendar),
        "signals": dict(counts), "reconciliation": reconciliation,
        "model_training_eligible_rows": 0,
        "reason": ("No verified complete as-of history window, no pre-match seed "
                   "temporal attestation and no prospective feature ablation."),
    }
    return signals, report


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, action="append")
    parser.add_argument("--calendar", type=Path,
                        help="Optional read-only monthly unique-tournament index")
    parser.add_argument("--history-dir", type=Path,
                        help="Optional read-only canonical history; never imports")
    parser.add_argument("--out", type=Path,
                        default=Path(".cache/tbt/tennisapi-prediction-research"))
    args = parser.parse_args()
    history = None
    if args.history_dir is not None:
        from tbt.data.history_snapshot import load_partitions
        history = load_partitions(args.history_dir)
    rows, report = audit(args.source, history=history, calendar=args.calendar)
    args.out.mkdir(parents=True, exist_ok=True)
    dest = args.out / "source-native-signals.jsonl"
    dest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8")
    report["sidecar_sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
