"""Build a verified Sets/Games score corpus for players on the current BlinQ board.

Historical S/G data follows a strict fact-first contract:
- player identity must match the provider event detail;
- per-set score must be structured and internally consistent;
- historical BO3/BO5 is accepted only from explicit provider data or the final
  structured score itself (winner reached 2 or 3 sets);
- tour/tournament heuristics are never used for completed history;
- ambiguous/conflicting rows fail closed and are reported.

Normal mode is incremental and idempotent. ``--rebuild-existing`` can be used as
an explicit one-off verification sweep; with ``--force-provider-refresh`` it
re-fetches event detail instead of reusing the local 30-day response cache.
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
from tbt.data.history_safety import sanitize_history_identities
from tbt.errors import ProviderError
from tbt.match_format import exact_best_of_from_score_stats, provider_best_of_from_context
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.score_enrichment import SCORE_SCHEMA_VERSION, ScoreEnricher
from tbt.services.sg_selection import select_sg_picks


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
    """Require the complete score schema used by S/G and LIVE Set-2 models."""
    stats = match.stats if isinstance(match.stats, dict) else {}
    try:
        sets = float(stats.get("total_sets"))
        games = float(stats.get("total_games"))
        p1_second = float(stats.get("p1_second_set_won"))
        p2_second = float(stats.get("p2_second_set_won"))
        float(stats.get("p1_set1_games")); float(stats.get("p2_set1_games"))
        float(stats.get("p1_set2_games")); float(stats.get("p2_set2_games"))
    except (TypeError, ValueError):
        return False
    return sets >= 2 and games >= 12 and round(p1_second + p2_second) == 1


def _format_fact(match) -> tuple[int | None, str]:
    """Return a verified historical BO3/BO5 fact, or fail closed."""
    if not _has_score(match):
        return None, "score_unavailable"
    stats = match.stats if isinstance(match.stats, dict) else {}
    score_best_of, score_source = exact_best_of_from_score_stats(stats)
    if score_best_of not in {3, 5}:
        return None, score_source
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    provider_best_of = provider_best_of_from_context(raw)
    if provider_best_of in {3, 5} and provider_best_of != score_best_of:
        return None, "provider_score_conflict"
    if provider_best_of in {3, 5}:
        return provider_best_of, "provider_detail"
    return score_best_of, score_source


def _training_ready(match) -> bool:
    value, _ = _format_fact(match)
    return value in {3, 5}


def _coverage(matches, player_ids: set[str], cutoff: datetime) -> dict[str, int]:
    counts = {player_id: 0 for player_id in player_ids}
    for match in matches:
        if match.scheduled_at >= cutoff or str(match.status or "").lower() in EXCLUDED:
            continue
        if not _training_ready(match):
            continue
        for player_id in {str(match.player1_id), str(match.player2_id)} & player_ids:
            counts[player_id] += 1
    return counts


def _normalize_existing_formats(matches) -> dict[str, object]:
    """Migrate existing structured scores to the explicit format contract.

    This migration consumes zero API requests and is idempotent. It never uses
    tour/tournament heuristics for completed history. A final structured score is
    itself an exact format fact; an explicit provider value must agree with it.
    """
    changed_years: set[int] = set()
    repaired = 0
    provider_verified = 0
    score_verified = 0
    conflicts = 0
    unsupported = 0

    for match in matches:
        if not _has_score(match):
            continue
        stats = match.stats if isinstance(match.stats, dict) else {}
        exact, score_source = exact_best_of_from_score_stats(stats)
        if exact not in {3, 5}:
            unsupported += 1
            continue

        raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        provider_value = provider_best_of_from_context(raw)
        format_marker = dict(raw.get("_tbt_match_format") or {}) if isinstance(raw.get("_tbt_match_format"), dict) else {}
        score_marker = dict(raw.get("_tbt_score") or {}) if isinstance(raw.get("_tbt_score"), dict) else {}
        updated = dict(raw)

        if provider_value in {3, 5} and provider_value != exact:
            conflicts += 1
            format_marker.update({
                "schema": 2,
                "status": "conflict",
                "best_of": None,
                "provider_best_of": provider_value,
                "score_best_of": exact,
                "source": "provider_vs_finished_score",
            })
            updated["_tbt_match_format"] = format_marker
            if score_marker:
                score_marker.update({
                    "status": "format_conflict",
                    "best_of": None,
                    "best_of_source": "provider_vs_finished_score_conflict",
                    "format_verified": False,
                })
                updated["_tbt_score"] = score_marker
            changed = match.best_of is not None or updated != raw
            match.best_of = None
            if changed:
                match.provider_payload = updated
                changed_years.add(match.scheduled_at.year)
            continue

        authoritative = provider_value or exact
        source = "provider_detail" if provider_value else score_source
        if provider_value:
            provider_verified += 1
        else:
            score_verified += 1

        format_marker.update({
            "schema": 2,
            "status": "verified",
            "best_of": authoritative,
            "source": source,
        })
        updated["_tbt_match_format"] = format_marker
        if score_marker:
            # Preserve the original event-detail provenance while adding the
            # canonical format proof used by downstream S/G consumers.
            score_marker.update({
                "best_of": authoritative,
                "best_of_source": source,
                "format_verified": True,
            })
            updated["_tbt_score"] = score_marker

        changed = match.best_of != authoritative or updated != raw
        if match.best_of != authoritative:
            match.best_of = authoritative
            repaired += 1
        if changed:
            match.provider_payload = updated
            changed_years.add(match.scheduled_at.year)

    return {
        "repaired": repaired,
        "provider_verified": provider_verified,
        "score_verified": score_verified,
        "conflicts": conflicts,
        "unsupported": unsupported,
        "changed_years": changed_years,
    }


def _write_dry_run(cache: Path, matches, feed: dict, now: datetime) -> dict[str, object]:
    upcoming = feed.get("upcoming") if isinstance(feed.get("upcoming"), list) else []
    cards, report = select_sg_picks(matches, upcoming, now=now)
    markets = Counter(str(card.get("market") or "unknown") for card in cards if isinstance(card, dict))
    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected": len(cards),
        "by_market": dict(markets),
        "report": report,
    }
    (cache / "sg_projection_dry_run.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument("--target-samples", type=int, default=24)
    parser.add_argument("--max-requests", type=int, default=2500)
    parser.add_argument(
        "--rebuild-existing", action="store_true",
        help="Re-verify existing S/G rows for current-board players instead of only filling gaps",
    )
    parser.add_argument(
        "--force-provider-refresh", action="store_true",
        help="Bypass the local event-detail cache; intended only for an explicit rebuild run",
    )
    args = parser.parse_args()
    if not 60 <= args.lookback_days <= 2500:
        parser.error("lookback-days must be 60..2500")
    if not 6 <= args.target_samples <= 80:
        parser.error("target-samples must be 6..80")
    if not 1 <= args.max_requests <= 12000:
        parser.error("max-requests must be 1..12000")
    if args.force_provider_refresh and not args.rebuild_existing:
        parser.error("--force-provider-refresh requires --rebuild-existing")

    cache = ROOT / ".cache" / "tbt" / "sg-history"
    history_dir = cache / "history"
    prediction_dir = cache / "predictions"
    cache.mkdir(parents=True, exist_ok=True)
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    prediction_store = ReleaseStore(args.data_repository, "tbt-predictions-v1", prediction_dir)
    history_store.download()
    prediction_store.download(extra_names=("feed.json",), required_names=("feed.json",))

    feed = json.loads((prediction_dir / "feed.json").read_text(encoding="utf-8"))
    player_ids = _feed_player_ids(feed)
    if not player_ids:
        raise SystemExit("Current prediction feed contains no upcoming player IDs")

    matches, identity_safety = sanitize_history_identities(load_partitions(history_dir))
    if identity_safety.get("changed"):
        print(json.dumps({"history_safety": identity_safety}, ensure_ascii=False), flush=True)

    format_normalization = _normalize_existing_formats(matches)
    normalized_years = set(format_normalization.pop("changed_years", set()))
    if normalized_years:
        bundle: list[Path] = []
        for year in sorted(normalized_years):
            path, _ = sync_year_partition(
                matches, history_dir, year,
                extra_manifest={"coverage_status": "sg_format_verified_v2"},
            )
            if path is not None:
                bundle.append(path)
        manifest = history_dir / "history_manifest.json"
        if manifest.is_file():
            bundle.append(manifest)
        history_store.upload_bundle(bundle)
    print(json.dumps({"sg_format_normalization": format_normalization}, ensure_ascii=False), flush=True)

    now = datetime.now(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    oldest = cutoff - timedelta(days=args.lookback_days)
    before = _coverage(matches, player_ids, cutoff)
    current = dict(before)

    candidate_rows: list[tuple[int, float, object]] = []
    for match in matches:
        if not oldest <= match.scheduled_at < cutoff:
            continue
        if str(match.status or "").lower() in EXCLUDED:
            continue
        participants = {str(match.player1_id), str(match.player2_id)} & player_ids
        if not participants:
            continue

        ready = _training_ready(match)
        if not args.rebuild_existing:
            if ready:
                continue
            if not any(current[player_id] < args.target_samples for player_id in participants):
                continue

        raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        provider_fact = provider_best_of_from_context(raw) in {3, 5}
        # First repair missing/ambiguous score rows, then verify score-derived
        # format rows, then optionally refresh already provider-verified rows.
        priority = 0 if not ready else (1 if not provider_fact else 2)
        candidate_rows.append((priority, -match.scheduled_at.timestamp(), match))

    candidate_rows.sort(key=lambda item: (item[0], item[1], str(item[2].match_id)))
    candidates = [item[2] for item in candidate_rows]

    provider = RapidTennisClient(request_budget=None)
    provider.request_limit = args.max_requests
    enricher = ScoreEnricher(
        provider,
        cache / "event_cache.sqlite",
        force_refresh=args.force_provider_refresh,
    )
    report = Counter()
    changed_years: set[int] = set()
    processed_since_checkpoint = 0
    rejected: list[dict[str, str]] = []

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
                extra_manifest={"coverage_status": "sg_verified_scores_v3"},
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
                    "schema": 3,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "rebuild" if args.rebuild_existing else "incremental",
                    "force_provider_refresh": args.force_provider_refresh,
                    "score_schema": SCORE_SCHEMA_VERSION,
                    "target_players": len(player_ids),
                    "target_samples": args.target_samples,
                    "lookback_days": args.lookback_days,
                    "requests": provider.request_count,
                    "status": dict(report),
                    "coverage": current,
                    "rejected": rejected[-200:],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bundle.append(report_path)
        history_store.upload_bundle(bundle)
        changed_years.clear()
        processed_since_checkpoint = 0

    mutating_statuses = {
        "enriched", "unavailable", "unsupported", "unsupported_format", "format_conflict",
        "identity_mismatch",
    }

    try:
        for match in candidates:
            participants = {str(match.player1_id), str(match.player2_id)} & player_ids
            before_ready = _training_ready(match)
            try:
                status = enricher.enrich(match)
            except ProviderError as exc:
                # Only genuine provider/transport failures reach this branch.
                # Identity mismatches are persisted by ScoreEnricher as their own
                # fail-closed status so they do not masquerade as API errors.
                message = str(exc)
                lower = message.lower()
                report["provider_error"] += 1
                if "http 429" in lower:
                    report["provider_error_429"] += 1
                elif "rapidapi http 4" in lower:
                    report["provider_error_http_4xx"] += 1
                elif "rapidapi http 5" in lower or "request failed" in lower:
                    report["provider_error_transport_or_5xx"] += 1
                else:
                    report["provider_error_other"] += 1
                if len(rejected) < 1000:
                    rejected.append({"match_id": str(match.match_id), "error": message[:240]})
                continue

            report[status] += 1
            if status in mutating_statuses:
                changed_years.add(match.scheduled_at.year)
                processed_since_checkpoint += 1

            after_ready = _training_ready(match)
            if not before_ready and after_ready:
                for player_id in participants:
                    current[player_id] += 1

            if processed_since_checkpoint >= 100:
                checkpoint()
            if not args.rebuild_existing and current and all(value >= args.target_samples for value in current.values()):
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

    dry_run = _write_dry_run(cache, matches, feed, now)
    after = _coverage(matches, player_ids, cutoff)
    summary = {
        "schema": 3,
        "mode": "rebuild" if args.rebuild_existing else "incremental",
        "force_provider_refresh": args.force_provider_refresh,
        "score_schema": SCORE_SCHEMA_VERSION,
        "target_players": len(player_ids),
        "candidates": len(candidates),
        "requests": provider.request_count,
        "status": dict(report),
        "before_min_samples": min(before.values(), default=0),
        "after_min_samples": min(after.values(), default=0),
        "players_ready": sum(value >= args.target_samples for value in after.values()),
        "target_samples": args.target_samples,
        "format_normalization": format_normalization,
        "dry_run": {
            "selected": dry_run.get("selected", 0),
            "by_market": dry_run.get("by_market", {}),
            "history_matches_with_structured_score": (dry_run.get("report") or {}).get("history_matches_with_structured_score"),
            "missing_best_of": (dry_run.get("report") or {}).get("missing_best_of"),
        },
        "rejected_count": len(rejected),
    }
    (cache / "sg_run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
