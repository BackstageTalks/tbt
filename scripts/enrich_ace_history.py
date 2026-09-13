"""Target Aces/Double-Fault statistics for players in the current prediction feed.

Unlike the generic historical statistics pass, this script spends the request
budget on recent matches involving players who are actually on the current
BlinQ board. It writes the canonical counts back to tbt-data-v1, so later
refreshes can build Ace Picks without additional live statistics calls.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions, sync_year_partition
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.statistics_enrichment import StatisticsEnricher


EXCLUDED = {"retired", "walkover", "walk over", "cancelled", "canceled", "abandoned"}


def _feed_player_ids(feed: dict) -> set[str]:
    ids: set[str] = set()
    for row in feed.get("upcoming", []) if isinstance(feed.get("upcoming"), list) else []:
        if not isinstance(row, dict):
            continue
        for key in ("player1", "player2"):
            player = row.get(key)
            if isinstance(player, dict):
                value = str(player.get("id") or "").strip()
                if value:
                    ids.add(value)
    return ids


def _has_counts(match, player_id: str, market: str) -> bool:
    stats = match.stats if isinstance(match.stats, dict) else {}
    if str(match.player1_id) == player_id:
        value = stats.get(f"p1_{market}")
    elif str(match.player2_id) == player_id:
        value = stats.get(f"p2_{market}")
    else:
        return False
    try:
        return float(value) >= 0
    except (TypeError, ValueError):
        return False


def _coverage(matches, player_ids: set[str], cutoff: datetime) -> dict[str, dict[str, int]]:
    counts = {player_id: {"aces": 0, "double_faults": 0} for player_id in player_ids}
    for match in matches:
        if match.scheduled_at >= cutoff or str(match.status or "").lower() in EXCLUDED:
            continue
        participants = {str(match.player1_id), str(match.player2_id)} & player_ids
        for player_id in participants:
            for market in ("aces", "double_faults"):
                if _has_counts(match, player_id, market):
                    counts[player_id][market] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--lookback-days", type=int, default=550)
    parser.add_argument("--target-samples", type=int, default=18)
    parser.add_argument("--max-requests", type=int, default=2500)
    args = parser.parse_args()
    if not 30 <= args.lookback_days <= 2000:
        parser.error("lookback-days must be 30..2000")
    if not 5 <= args.target_samples <= 60:
        parser.error("target-samples must be 5..60")
    if not 1 <= args.max_requests <= 12000:
        parser.error("max-requests must be 1..12000")

    cache = ROOT / ".cache" / "tbt" / "ace-history"
    history_dir = cache / "history"
    prediction_dir = cache / "predictions"
    history = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    predictions = ReleaseStore(args.data_repository, "tbt-predictions-v1", prediction_dir)
    history.download()
    predictions.download(extra_names=("feed.json",), required_names=("feed.json",))

    feed = json.loads((prediction_dir / "feed.json").read_text(encoding="utf-8"))
    player_ids = _feed_player_ids(feed)
    if not player_ids:
        raise SystemExit("Current prediction feed contains no upcoming player IDs")

    matches = load_partitions(history_dir)
    now = datetime.now(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    oldest = cutoff - timedelta(days=args.lookback_days)
    before = _coverage(matches, player_ids, cutoff)
    current_coverage = {player_id: dict(values) for player_id, values in before.items()}

    candidates = []
    for match in sorted(matches, key=lambda item: item.scheduled_at, reverse=True):
        if not oldest <= match.scheduled_at < cutoff:
            continue
        if str(match.status or "").lower() in EXCLUDED:
            continue
        participants = {str(match.player1_id), str(match.player2_id)} & player_ids
        if not participants:
            continue
        if not any(
            min(before[player_id]["aces"], before[player_id]["double_faults"]) < args.target_samples
            for player_id in participants
        ):
            continue
        candidates.append(match)

    provider = RapidTennisClient(request_budget=None)
    provider.request_limit = args.max_requests
    enricher = StatisticsEnricher(provider, cache / "statistics_cache.sqlite")
    report = Counter()
    changed_years: set[int] = set()
    processed_since_checkpoint = 0

    def checkpoint() -> None:
        nonlocal processed_since_checkpoint
        if not changed_years:
            return
        bundle: list[Path] = []
        for year in sorted(changed_years):
            path, _ = sync_year_partition(
                matches,
                history_dir,
                year,
                extra_manifest={"coverage_status": "ace_targeted_statistics"},
            )
            if path is not None:
                bundle.append(path)
        manifest = history_dir / "history_manifest.json"
        if manifest.is_file():
            bundle.append(manifest)
        report_path = history_dir / "ace_statistics_report.json"
        report_payload = {
            "schema": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_players": len(player_ids),
            "target_samples": args.target_samples,
            "lookback_days": args.lookback_days,
            "requests": provider.request_count,
            "status": dict(report),
            "coverage": current_coverage,
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        bundle.append(report_path)
        history.upload_bundle(bundle)
        changed_years.clear()
        processed_since_checkpoint = 0

    try:
        for match in candidates:
            participants = {str(match.player1_id), str(match.player2_id)} & player_ids
            before_flags = {
                player_id: {
                    market: _has_counts(match, player_id, market)
                    for market in ("aces", "double_faults")
                }
                for player_id in participants
            }
            # Skip a match that already has the desired count pair for all target
            # participants; schema-2 marker caching handles the rest safely.
            if participants and all(all(flags.values()) for flags in before_flags.values()):
                report["already_counted"] += 1
                continue
            status = enricher.enrich(match)
            report[status] += 1
            if status in {"enriched", "unavailable"}:
                changed_years.add(match.scheduled_at.year)
                processed_since_checkpoint += 1
            for player_id in participants:
                for market in ("aces", "double_faults"):
                    if not before_flags[player_id][market] and _has_counts(match, player_id, market):
                        current_coverage[player_id][market] += 1
            if processed_since_checkpoint >= 100:
                checkpoint()

            if all(
                min(values["aces"], values["double_faults"]) >= args.target_samples
                for values in current_coverage.values()
            ):
                report["target_reached"] = 1
                break
    except RequestBudgetExceeded:
        report["budget_stopped"] = 1
    finally:
        try:
            checkpoint()
        finally:
            enricher.close()
            provider.client.close()

    after = current_coverage
    summary = {
        "target_players": len(player_ids),
        "candidates": len(candidates),
        "requests": provider.request_count,
        "status": dict(report),
        "before_min_samples": min((min(v.values()) for v in before.values()), default=0),
        "after_min_samples": min((min(v.values()) for v in after.values()), default=0),
        "players_ready": sum(min(v.values()) >= args.target_samples for v in after.values()),
        "target_samples": args.target_samples,
    }
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
