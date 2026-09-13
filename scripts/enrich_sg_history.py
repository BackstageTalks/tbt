"""Target structured set/game score history for players on the current BlinQ board.

The canonical history intentionally does not retain raw provider responses. This
job fetches only recent event-detail rows for current upcoming players, extracts
verified per-set scores, and writes compact totals back into ``match.stats``.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions, sync_year_partition
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.score_enrichment import ScoreEnricher


EXCLUDED = {
    "retired", "walkover", "walk over", "cancelled", "canceled",
    "abandoned", "interrupted", "suspended", "postponed",
}


def _feed_player_ids(feed: dict) -> set[str]:
    ids: set[str] = set()
    rows = feed.get("upcoming") if isinstance(feed.get("upcoming"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("player1", "player2"):
            player = row.get(key)
            if isinstance(player, dict):
                value = str(player.get("id") or "").strip()
                if value:
                    ids.add(value)
    return ids


def _has_score(match) -> bool:
    stats = match.stats if isinstance(match.stats, dict) else {}
    try:
        sets = float(stats.get("total_sets"))
        games = float(stats.get("total_games"))
    except (TypeError, ValueError):
        return False
    return sets >= 2 and games >= 12


def _coverage(matches, player_ids: set[str], cutoff: datetime) -> dict[str, int]:
    counts = {player_id: 0 for player_id in player_ids}
    for match in matches:
        if match.scheduled_at >= cutoff or str(match.status or "").lower() in EXCLUDED:
            continue
        if not _has_score(match):
            continue
        for player_id in {str(match.player1_id), str(match.player2_id)} & player_ids:
            counts[player_id] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument("--target-samples", type=int, default=24)
    parser.add_argument("--max-requests", type=int, default=2500)
    args = parser.parse_args()
    if not 60 <= args.lookback_days <= 2500:
        parser.error("lookback-days must be 60..2500")
    if not 6 <= args.target_samples <= 80:
        parser.error("target-samples must be 6..80")
    if not 1 <= args.max_requests <= 12000:
        parser.error("max-requests must be 1..12000")

    cache = ROOT / ".cache" / "tbt" / "sg-history"
    history_dir = cache / "history"
    prediction_dir = cache / "predictions"
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    prediction_store = ReleaseStore(args.data_repository, "tbt-predictions-v1", prediction_dir)
    history_store.download()
    prediction_store.download(extra_names=("feed.json",), required_names=("feed.json",))

    feed = json.loads((prediction_dir / "feed.json").read_text(encoding="utf-8"))
    player_ids = _feed_player_ids(feed)
    if not player_ids:
        raise SystemExit("Current prediction feed contains no upcoming player IDs")

    matches = load_partitions(history_dir)
    now = datetime.now(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    oldest = cutoff - timedelta(days=args.lookback_days)
    before = _coverage(matches, player_ids, cutoff)
    current = dict(before)

    candidates = []
    for match in sorted(matches, key=lambda item: item.scheduled_at, reverse=True):
        if not oldest <= match.scheduled_at < cutoff:
            continue
        if str(match.status or "").lower() in EXCLUDED:
            continue
        participants = {str(match.player1_id), str(match.player2_id)} & player_ids
        if not participants or _has_score(match):
            continue
        if not any(current[player_id] < args.target_samples for player_id in participants):
            continue
        candidates.append(match)

    provider = RapidTennisClient(request_budget=None)
    provider.request_limit = args.max_requests
    enricher = ScoreEnricher(provider, cache / "event_cache.sqlite")
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
                extra_manifest={"coverage_status": "sg_targeted_scores"},
            )
            if path is not None:
                bundle.append(path)
        manifest = history_dir / "history_manifest.json"
        if manifest.is_file():
            bundle.append(manifest)
        report_path = history_dir / "sg_score_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "target_players": len(player_ids),
                    "target_samples": args.target_samples,
                    "lookback_days": args.lookback_days,
                    "requests": provider.request_count,
                    "status": dict(report),
                    "coverage": current,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        bundle.append(report_path)
        history_store.upload_bundle(bundle)
        changed_years.clear()
        processed_since_checkpoint = 0

    try:
        for match in candidates:
            participants = {str(match.player1_id), str(match.player2_id)} & player_ids
            before_has_score = _has_score(match)
            if before_has_score:
                report["already_counted"] += 1
                continue
            status = enricher.enrich(match)
            report[status] += 1
            if status in {"enriched", "unavailable", "unsupported"}:
                changed_years.add(match.scheduled_at.year)
                processed_since_checkpoint += 1
            if not before_has_score and _has_score(match):
                for player_id in participants:
                    current[player_id] += 1
            if processed_since_checkpoint >= 100:
                checkpoint()
            if all(value >= args.target_samples for value in current.values()):
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

    summary = {
        "target_players": len(player_ids),
        "candidates": len(candidates),
        "requests": provider.request_count,
        "status": dict(report),
        "before_min_samples": min(before.values(), default=0),
        "after_min_samples": min(current.values(), default=0),
        "players_ready": sum(value >= args.target_samples for value in current.values()),
        "target_samples": args.target_samples,
    }
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
