"""Pair private pre-match winner quotes to frozen sports scores without fuzzy IDs.

The FIRST 06:00+ local betting-day snapshot is fixed outcome-blind.
Neither result, projected winner nor bookmaker probabilities participate
in linking. Ambiguities are dropped, never guessed.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import gzip
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

BRATISLAVA = ZoneInfo("Europe/Bratislava")


def aware(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo and dt.utcoffset() is not None else None


def betting_day(value):
    return (value.astimezone(BRATISLAVA) - timedelta(hours=6)).date().isoformat()


def event_key(row, event_field):
    event = str(row.get(event_field) or "").strip()
    tour = str(row.get("tour") or "").strip().lower()
    ids = (str(row.get("player1_id") or ""), str(row.get("player2_id") or ""))
    if not event or not tour or not all(ids) or ids[0] == ids[1]:
        return None
    return (event, tour, tuple(sorted(ids)))


def quote_number(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and 1. < number <= 10000 else None


def strict_first_morning_quotes(scored, source_archives):
    """Return exact, time-valid winner quotes plus coverage diagnostic.

    Scored records are generated only from the frozen feature replay.
    Source archives must come from verified private releases; no raw odds
    join inferred from player names, tournament substrings or predicted side.
    """
    if scored.get("schema") != 1 or not isinstance(scored.get("rows"), list):
        raise ValueError("Frozen scored holdout is invalid")
    candidates = scored["rows"]
    lookup = {}
    ambiguous = set()
    for candidate in candidates:
        key = event_key(candidate, "provider_event_id")
        if key is None:
            continue
        if key in lookup:
            ambiguous.add(key)
        else:
            lookup[key] = candidate
    for key in ambiguous:
        lookup.pop(key, None)

    first = {}
    archive_pins = []
    invalid_snapshot_times = 0
    for source in source_archives:
        data = source["archive"]
        asset_sha = source["source_sha256"]
        if (data.get("schema") != 1 or not isinstance(data.get("snapshots"), list)
                or len(asset_sha) != 64 or not all(c in "0123456789abcdef" for c in asset_sha)):
            raise ValueError("Unverified or malformed private selector archive")
        archive_pins.append(asset_sha)
        for snapshot in data["snapshots"]:
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("rows"), list):
                continue
            at = aware(snapshot.get("generated_at"))
            if at is None:
                invalid_snapshot_times += 1
                continue
            local = at.astimezone(BRATISLAVA)
            if local.hour < 6:
                continue
            day = betting_day(at)
            candidate = (at, asset_sha, snapshot)
            if day not in first or at < first[day][0]:
                first[day] = candidate

    reasons = Counter()
    quotes = {}
    for day, (snapshot_at, source_hash, snapshot) in sorted(first.items()):
        for row in snapshot["rows"]:
            if not isinstance(row, dict):
                continue
            players = [row.get(k) if isinstance(row.get(k), dict) else {}
                       for k in ("player1", "player2")]
            normalized = {
                "event_id": row.get("event_id"),
                "tour": row.get("tour"),
                "player1_id": players[0].get("id"),
                "player2_id": players[1].get("id"),
            }
            key = event_key(normalized, "event_id")
            if key is None or key not in lookup:
                reasons["no_exact_identity"] += 1
                continue
            match = lookup[key]
            match_id = str(match["match_id"])
            start = aware(match.get("scheduled_at"))
            original_start = aware(row.get("scheduled_at"))
            if start is None or original_start is None or betting_day(start) != day:
                reasons["missing_or_mismatched_fixture_day"] += 1
                continue
            if abs((start - original_start).total_seconds()) > 45*60:
                reasons["start_drift_over_45m"] += 1
                continue
            if snapshot_at >= min(start, original_start):
                reasons["snapshot_after_start"] += 1
                continue
            market = row.get("two_way_market")
            if not isinstance(market, dict):
                reasons["missing_two_way_market"] += 1
                continue
            captured = aware(market.get("captured_at"))
            if captured is None or not captured <= snapshot_at or captured >= min(start, original_start):
                reasons["unverified_prestart_quote_time"] += 1
                continue
            odds = [quote_number(market.get("player1_odds")),
                    quote_number(market.get("player2_odds"))]
            if any(x is None for x in odds) or not str(market.get("provider_id") or "").strip():
                reasons["missing_real_two_way_quote"] += 1
                continue
            ids = [str(players[0].get("id")), str(players[1].get("id"))]
            exact = [str(match["player1_id"]), str(match["player2_id"])]
            if ids == exact[::-1]:
                odds.reverse()
            elif ids != exact:
                reasons["orientation_conflict"] += 1
                continue
            if match_id in quotes:
                # Never keep an arbitrary duplicate after a second exact match.
                quotes[match_id] = None
                reasons["duplicate_verified_match"] += 1
                continue
            quotes[match_id] = {
                "match_id": match_id,
                "player1_id": exact[0],
                "player2_id": exact[1],
                "captured_at": captured.isoformat(),
                "odds_player1": odds[0],
                "odds_player2": odds[1],
                "source_snapshot_generated_at": snapshot_at.isoformat(),
                "source_sha256": source_hash,
                "provider_id": str(market["provider_id"]),
            }
    verified = [r for r in quotes.values() if r is not None]
    return verified, {
        "schema": 1, "selection": "first_snapshot_after_0600_local",
        "scored_rows": len(candidates),
        "scored_provider_event_ids": sum(event_key(r, "provider_event_id") is not None for r in candidates),
        "ambiguous_scored_event_keys": len(ambiguous),
        "source_archives_sha256": sorted(set(archive_pins)),
        "days_with_first_morning_snapshot": len(first),
        "invalid_snapshot_timestamps": invalid_snapshot_times,
        "exact_time_verified_quotes": len(verified),
        "rejections": dict(sorted(reasons.items())),
        "not_published_top_evidence": True,
        "outcomes_used_for_quote_join": False,
    }


def read_gzip_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def run(args):
    from release_store import ReleaseStore
    from evaluate_paired_top_selection import evaluate

    root = Path(args.work_dir)
    candidate_tag = args.candidate_tag
    if not candidate_tag.startswith("blinq-candidate-frozen-"):
        raise ValueError("Only a pinned private candidate release is supported")
    model_store = ReleaseStore("BackstageTalks/tbt-data", candidate_tag,
                               root / "candidate")
    model_store.download(required_names=("paired_top_holdout.json.gz",),
                         require_bundle_manifest=True)
    pair_path = root / "candidate" / "paired_top_holdout.json.gz"
    score_bytes = pair_path.read_bytes()
    scored = read_gzip_json(pair_path)
    selection_store = ReleaseStore("BackstageTalks/tbt-data", "tbt-predictions-v1",
                                   root / "snapshots")
    months = ("selection_candidates_2026-10.json.gz",
              "selection_candidates_2026-11.json.gz")
    selection_store.download(required_names=months, require_bundle_manifest=True)
    sources = []
    for name in months:
        path = root / "snapshots" / name
        sources.append({"archive": read_gzip_json(path),
                        "source_sha256": sha256(path.read_bytes()).hexdigest()})
    quotes, join = strict_first_morning_quotes(scored, sources)
    analysis = evaluate(scored, quotes)
    output = {
        "status": "RESEARCH_ONLY_PREVIOUSLY_INSPECTED_HOLDOUT",
        "candidate_release": candidate_tag,
        "paired_scores_sha256": sha256(score_bytes).hexdigest(),
        "quote_linkage": join,
        "replay": analysis,
        "production_swapped": False,
        "api_requests": 0,
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False,
                                 allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({
        "status": output["status"],
        "exact_time_verified_quotes": join["exact_time_verified_quotes"],
        "comparison": {k: {
            "qualified": v["qualified"],
            "all_qualified": v["all_qualified"],
            "top_3": v["top_3"],
            "days_with_3plus": v["days_with_3plus"],
        } for k, v in analysis["comparison"].items()},
    }, allow_nan=False))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-tag", required=True)
    parser.add_argument("--work-dir", default=".cache/tbt/paired-top-quote-research")
    parser.add_argument("--out", default=".cache/tbt/paired-top-quote-research-report.json")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
