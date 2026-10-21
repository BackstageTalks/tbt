"""Download/resume TennisApi history into private GitHub Release partitions."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from tbt.config import settings
from tbt.errors import ProviderError
from tbt.data.history_snapshot import (
    load_partitions,
    merge_matches,
    sync_year_partition,
    _provider_event_id,
)
from tbt.data.history_safety import sanitize_history_identities, quarantine_budget, merge_trusted_history_batch
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.statistics_enrichment import StatisticsEnricher
from tbt.services.statistics_enrichment import STATISTICS_SCHEMA_VERSION
from tbt.services.statistics_gapfill import event_id, missing_fields, retry_due
from tbt.services.tennisapi_extras_enrichment import needs_extras, enrich_event_extras


from release_store import ReleaseStore
from date_window import history_window
from audit_statistics_inventory import _quality_ready, statistics_value_change
from adaptive_statistics_queue import AdaptiveStatisticsQueue

# Priorities from five independently read-back VERIFIED CDB statistics runs on
# 2026-10-20 (11,564 paid calls; 135,213 persisted new values). WTA 2023
# earned a high-yield slot alongside WTA 2024/2022 and ATP 2024.
# These are initial ordering priors, not fixed quota shares: the online queue
# relearns from paid CDB gains each run, with >=25% baseline exploration.
# ATP 2025 and 2026 remain available for exploration, never guessed or forced.
VERIFIED_HIGH_YIELD_COHORTS = (("wta", 2024), ("wta", 2023), ("wta", 2022), ("atp", 2024))


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)



def merge_match(existing, incoming):
    """Compatibility helper for one unambiguous logical match."""
    if existing is None:
        return incoming
    merged = merge_matches([existing], [incoming])
    if len(merged) != 1:
        raise ValueError("Cannot merge conflicting match identities")
    result = merged[0]
    return result if result.player1_id == incoming.player1_id else result.swapped()


def _history_identity_counter(rows):
    from collections import Counter
    return Counter(
        (
            str(match.match_id or ""),
            str(_provider_event_id(match) or ""),
            match.scheduled_at.isoformat(),
            str(match.player1_id or ""),
            str(match.player2_id or ""),
        )
        for match in rows
    )


def _merge_completed_rows(matches, completed_rows, provider_years, quarantine=None):
    """Merge a provider batch without letting one bad identity block the day."""
    before = list(matches.values()) if isinstance(matches, dict) else list(matches)
    final, accepted_incoming, safety = merge_trusted_history_batch(before, completed_rows)

    if safety.get("quarantined_rows"):
        if quarantine is not None:
            quarantine.extend(safety.get("rows") or [])
        print(json.dumps({"provider_identity_quarantine": safety}, ensure_ascii=False), flush=True)

    if isinstance(matches, dict):
        matches.clear()
        matches.update({match.match_id: match for match in final})
    else:
        matches[:] = final

    for match in accepted_incoming:
        provider_id = _provider_event_id(match)
        if provider_id is not None:
            provider_years[str(provider_id)] = (
                match.scheduled_at.astimezone(timezone.utc).year
            )

    years = {
        int(match.scheduled_at.astimezone(timezone.utc).year)
        for match in [*before, *final]
    }
    affected_years = set()
    for year in years:
        left = _history_identity_counter(
            m for m in before if m.scheduled_at.astimezone(timezone.utc).year == year
        )
        right = _history_identity_counter(
            m for m in final if m.scheduled_at.astimezone(timezone.utc).year == year
        )
        if left != right:
            affected_years.add(year)
    return affected_years


def download_days(provider, matches, progress, start, end, checkpoint, quarantine=None):
    """Newest first. Mark a day complete only after BOTH tours succeed."""
    done = set(progress.get("completed_days", []))
    current = list(matches.values()) if isinstance(matches, dict) else list(matches)
    provider_years = {
        provider_id: match.scheduled_at.astimezone(timezone.utc).year
        for match in current
        if (provider_id := _provider_event_id(match)) is not None
    }
    day = end
    count = 0
    while day >= start:
        if day.isoformat() not in done:
            rows = []
            for tour in ("atp", "wta"):
                rows.extend(provider.matches_for_day(tour, day, historical=True))
                provider_events = getattr(provider, "historical_event_quarantine", None)
                if quarantine is not None and isinstance(provider_events, list) and provider_events:
                    quarantine.extend(provider_events)
                    provider_events.clear()
            completed_rows = [match for match in rows if match.is_completed]
            affected_years = set()
            if completed_rows:
                affected_years = _merge_completed_rows(
                    matches, completed_rows, provider_years, quarantine
                )
            done.add(day.isoformat())
            progress["completed_days"] = sorted(done)
            count += 1
            checkpoint(affected_years, count % 7 == 0)
            print(json.dumps({"completed_day": day.isoformat(), "rows": len(rows),
                              "requests": provider.request_count}), flush=True)
        day -= timedelta(days=1)



def reopen_history_gap_days(matches, progress, start, end, existing_years):
    """Re-open progress dates when a requested year is missing or catastrophically partial."""
    requested_years = set(range(start.year, end.year + 1))
    missing_years = requested_years - set(existing_years)

    represented_days = {}
    values = matches.values() if isinstance(matches, dict) else matches
    for match in values:
        match_day = match.scheduled_at.astimezone(timezone.utc).date()
        if start <= match_day <= end:
            represented_days.setdefault(match_day.year, set()).add(match_day.isoformat())

    completed_by_year = {}
    valid_completed = []
    invalid_completed = []
    for raw_day in progress.get("completed_days", []):
        try:
            parsed_day = date.fromisoformat(str(raw_day))
        except ValueError:
            invalid_completed.append(raw_day)
            continue
        valid_completed.append((raw_day, parsed_day))
        if start <= parsed_day <= end:
            completed_by_year.setdefault(parsed_day.year, set()).add(parsed_day.isoformat())

    suspicious_partial_years = set()
    partial_coverage = {}
    for year in sorted(requested_years & set(existing_years)):
        completed = completed_by_year.get(year, set())
        if len(completed) < 14:
            continue
        represented = represented_days.get(year, set())
        represented_completed = completed & represented
        ratio = len(represented_completed) / max(1, len(completed))
        # A healthy tennis year has matches on most completed calendar days.
        # Below 50% is intentionally conservative and catches catastrophic
        # partial-year uploads without re-fetching ordinary no-match days.
        if ratio < 0.50:
            suspicious_partial_years.add(year)
            partial_coverage[str(year)] = {
                "completed_days": len(completed),
                "represented_completed_days": len(represented_completed),
                "represented_ratio": round(ratio, 4),
            }

    kept_days = list(invalid_completed)
    reopened_days = []
    for raw_day, parsed_day in valid_completed:
        reopen = False
        if start <= parsed_day <= end and parsed_day.year in missing_years:
            reopen = True
        elif start <= parsed_day <= end and parsed_day.year in suspicious_partial_years:
            if parsed_day.isoformat() not in represented_days.get(parsed_day.year, set()):
                reopen = True
        if reopen:
            reopened_days.append(raw_day)
        else:
            kept_days.append(raw_day)

    if reopened_days:
        progress["completed_days"] = sorted(kept_days)
    return {
        "missing_partition_years": sorted(missing_years),
        "partial_partition_years": sorted(suspicious_partial_years),
        "partial_partition_coverage": partial_coverage,
        "reopened_days": reopened_days,
    }


def _record_targeted_statistics_outcome(segments, unavailable_reasons, match, status,
                                        requests, value_change):
    """Account for actual per-match provider spend and CDB gains by tour/year."""
    key = f"{str(match.tour or 'unknown').lower()}:{match.scheduled_at.year}"
    counts = segments.setdefault(key, Counter())
    counts["processed_matches"] += 1
    counts[f"status_{status}"] += 1
    counts["api_requests_including_retries"] += requests
    source = "api" if requests else "local_or_cache"
    if requests:
        counts["matches_with_provider_requests"] += 1
    for metric in ("new_statistic_values", "new_quality_ready_rows", "new_ace_df_values"):
        value = int(value_change.get(metric, 0))
        counts[metric] += value
        counts[f"{source}_{metric}"] += value
    if status == "unavailable":
        marker = (getattr(match, "provider_payload", None) or {}).get("_tbt_statistics")
        reason = marker.get("reason") if isinstance(marker, dict) else None
        # Bound categories to the provider adapter's known coverage states;
        # never emit raw provider payloads or player identities in this report.
        if reason not in {"no_supported_fields", "missing_unambiguous_all_period",
                          "empty_whole_match_statistics", "provider_event_not_finished"}:
            reason = "unspecified"
        counts[f"unavailable_{reason}"] += 1
        unavailable_reasons[reason] += 1


def _statistics_segment_yield(segments):
    """Compact, denominator-aware outcome evidence for the next API schedule."""
    result = {}
    for key, counts in sorted(segments.items(), reverse=True):
        requests = counts["api_requests_including_retries"]
        result[key] = {
            **dict(counts),
            "api_new_statistic_values_per_1000_requests": (
                1000 * counts["api_new_statistic_values"] / requests if requests else None
            ),
            "api_new_quality_ready_rows_per_1000_requests": (
                1000 * counts["api_new_quality_ready_rows"] / requests if requests else None
            ),
        }
    return result


def _balanced_targeted_gap_order(candidates, bucket_total, bucket_ready):
    """Keep 2024-26 front and centre without abandoning productive older cohorts.

    The 20-slot deterministic baseline allocates 8 slots to verified 2024
    cohorts, 6 to under-covered 2025-26 cohorts, 3 to verified 2022-23
    providers, 1 to other underserved historical cohorts, and 2 to broad
    exploration. These are *baseline* slots, not fixed paid API quotas: the
    online adaptive queue still follows measured new CDB values per call.
    Canonical identity and provider retry/cooldown gates ran before this step.
    """
    from collections import defaultdict, deque

    families = ("recent_verified", "recent_gap", "historic_verified",
                "historic_gap", "other")
    grouped = {name: defaultdict(list) for name in families}
    for candidate in candidates:
        match = candidate[-1]
        tour = str(match.tour or "unknown").lower()
        year = int(match.scheduled_at.year)
        bucket = (tour, year)
        stats = match.stats if isinstance(match.stats, dict) else {}
        incomplete_rates = not (
            _quality_ready(stats, "p1") and _quality_ready(stats, "p2")
        )
        coverage = bucket_ready[bucket] / max(1, bucket_total[bucket])
        if candidate[0] == 0:
            family = "recent_verified" if year >= 2024 else "historic_verified"
        elif (incomplete_rates and 2025 <= year <= 2026 and
              tour in {"atp", "wta"} and coverage < 0.75):
            family = "recent_gap"
        elif (incomplete_rates and 2022 <= year <= 2023 and
              tour in {"atp", "wta"} and coverage < 0.55):
            family = "historic_gap"
        else:
            family = "other"
        grouped[family][bucket].append(candidate)

    pending = {}
    years = {}
    for family in families:
        pending[family] = {
            bucket: deque(sorted(rows, key=lambda r: (
                r[4], r[2], r[3], r[5], r[6], r[7]
            )))
            for bucket, rows in grouped[family].items()
        }

        def bucket_priority(bucket):
            if family == "recent_gap":
                return (0, bucket_ready[bucket] / max(1, bucket_total[bucket]),
                        -bucket[1], bucket[0])
            prior = (VERIFIED_HIGH_YIELD_COHORTS.index(bucket)
                     if family in {"recent_verified", "historic_verified"}
                     and bucket in VERIFIED_HIGH_YIELD_COHORTS
                     else len(VERIFIED_HIGH_YIELD_COHORTS))
            return (1, prior, -bucket[1], bucket[0])

        years[family] = deque(sorted(pending[family], key=bucket_priority))

    # Interleave families so each gets early paid samples before adaptation.
    # Of 20 available slots: 14 recent, 4 historical and 2 other. Empty
    # families simply yield their slots; no requests are made to fill quotas.
    schedule = (
        "recent_verified", "recent_gap", "recent_verified", "historic_verified",
        "recent_gap", "recent_verified", "historic_gap", "recent_gap",
        "recent_verified", "other",
        "recent_verified", "recent_gap", "historic_verified", "recent_verified",
        "recent_gap", "recent_verified", "historic_verified", "recent_gap",
        "recent_verified", "other",
    )
    result = []
    while len(result) < len(candidates):
        advanced = False
        for family in schedule:
            if not years[family]:
                continue
            bucket = years[family].popleft()
            queue = pending[family][bucket]
            result.append(queue.popleft())
            advanced = True
            if queue:
                years[family].append(bucket)
        if not advanced:
            raise RuntimeError("Targeted gap queue stopped before consuming candidates")
    return result


def _statistics_candidates(matches, start, end, *, targeted=False, historical_high_yield=False, target_tour=None):
    """Prioritize verified gaps; optional high-yield historical cohort first."""
    if historical_high_yield and not targeted:
        raise ValueError("High-yield priority requires identity-checked targeted statistics")
    if target_tour not in (None, "atp", "wta"):
        raise ValueError("Unsupported statistics target tour")
    in_window = [
        match for match in matches
        if (match.is_completed and start <= match.scheduled_at.date() <= end
            and (target_tour is None or str(match.tour or "").lower() == target_tour))
    ]
    bucket_total = Counter()
    bucket_ready = Counter()
    for match in in_window:
        key = (str(match.tour or "unknown").lower(), int(match.scheduled_at.year))
        bucket_total[key] += 1
        stats = match.stats if isinstance(match.stats, dict) else {}
        if _quality_ready(stats, "p1") and _quality_ready(stats, "p2"):
            bucket_ready[key] += 1

    candidates = []
    skipped = Counter()
    for match in in_window:
        stats = match.stats if isinstance(match.stats, dict) else {}
        p1_ready = _quality_ready(stats, "p1")
        p2_ready = _quality_ready(stats, "p2")
        if targeted:
            if not missing_fields(match):
                skipped["target_fields_present"] += 1
                continue
            if event_id(match) is None:
                skipped["missing_or_conflicting_event_id"] += 1
                continue
            if not retry_due(match, STATISTICS_SCHEMA_VERSION):
                skipped["retry_not_due"] += 1
                continue
        elif p1_ready and p2_ready:
            continue
        key = (str(match.tour or "unknown").lower(), int(match.scheduled_at.year))
        coverage = bucket_ready[key] / max(1, bucket_total[key])
        populated = sum(value is not None for value in stats.values())
        partial_priority = 0 if (p1_ready or p2_ready) else 1 if populated else 2
        # Within a recent year, complete missing serve/return quality before
        # spending the same budget on ace/DF-only gaps in already-ready rows.
        # Existing complete, verified identity also saves an event-detail call.
        identity = (getattr(match, "provider_payload", None) or {}).get("_tbt_event_identity") if targeted else None
        verified_identity = (
            isinstance(identity, dict)
            and identity.get("event_id") == event_id(match)
            and identity.get("status") == "finished"
            and {identity.get("home"), identity.get("away")}
                == {match.player1_id, match.player2_id}
            and identity.get("home") != identity.get("away")
        ) if targeted else False
        # Opt-in hourly only: use currently evidenced productive cohorts,
        # not the historic ATP-2025 preference after repeated zero-yield calls.
        # Prefer incomplete serve/return quality; ace/DF-only rows are explored
        # by the baseline and adaptively if empirical value warrants it.
        high_yield = bool(historical_high_yield
                          and key in VERIFIED_HIGH_YIELD_COHORTS
                          and not (p1_ready and p2_ready))
        candidates.append((
            0 if high_yield else 1,
            -match.scheduled_at.year if targeted else coverage,
            int(p1_ready and p2_ready) if targeted else 0,
            partial_priority,
            int(not verified_identity) if targeted else 0,
            -populated,
            -match.scheduled_at.timestamp(),
            str(match.match_id),
            match,
        ))
    candidates.sort(key=lambda row: row[:-1])
    if historical_high_yield:
        candidates = _balanced_targeted_gap_order(candidates, bucket_total, bucket_ready)
    first_1000 = candidates[:1000]
    priority_preview = dict(Counter(
        f"{str(entry[-1].tour or 'unknown').lower()}:{entry[-1].scheduled_at.year}"
        for entry in first_1000
    )) if historical_high_yield else {}
    return [row[-1] for row in candidates], {
        "window_completed": len(in_window),
        "already_quality_ready": sum(bucket_ready.values()),
        "candidate_rows": len(candidates),
        "targeted": targeted,
        "historical_high_yield": historical_high_yield,
        "preferred_verified_cohort": "wta:2024:serve_return_incomplete" if historical_high_yield else None,
        "verified_high_yield_cohorts": [f"{tour}:{year}" for tour, year in VERIFIED_HIGH_YIELD_COHORTS] if historical_high_yield else [],
        "priority_policy": "8_recent_verified_6_recent_gap_3_historic_verified_1_historic_gap_2_other" if historical_high_yield else None,
        "first_1000_by_tour_year": priority_preview,
        "recent_focus_years": [2024, 2025, 2026] if historical_high_yield else [],
        "planned_recent_baseline_share_if_all_families_available": 0.7 if historical_high_yield else None,
        "skipped": dict(skipped),
        "bucket_coverage": {
            f"{tour}:{year}": {
                "completed": bucket_total[(tour, year)],
                "quality_ready": bucket_ready[(tour, year)],
                "quality_ready_rate": round(
                    bucket_ready[(tour, year)] / max(1, bucket_total[(tour, year)]), 6
                ),
            }
            for tour, year in sorted(bucket_total)
        },
    }




def _extras_candidates(matches, start, end):
    """Newest season first (2026, then 2025, ...), verified identity within year.

    The daily extras backlog must not let a previously verified old event jump
    ahead of a 2026 event. Completed/cooldown-covered matches are skipped by
    needs_extras; the queue naturally advances to older seasons when current
    season coverage is exhausted, without re-spending calls on cached markers.
    """
    rows = [m for m in matches
            if start <= m.scheduled_at.date() <= end and needs_extras(m)]
    def key(match):
        raw = match.provider_payload or {}
        ident = raw.get("_tbt_event_identity") if isinstance(raw, dict) else None
        eid = event_id(match)
        verified = (isinstance(ident, dict) and ident.get("event_id") == eid
                    and ident.get("status") == "finished"
                    and {ident.get("home"), ident.get("away")}
                    == {match.player1_id, match.player2_id})
        return (-match.scheduled_at.year, int(not verified),
                -match.scheduled_at.timestamp(), str(match.match_id))
    return sorted(rows, key=key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None, help="Optional oldest date; overrides lookback")
    parser.add_argument("--end", default=None, help="Optional newest date; default yesterday UTC")
    parser.add_argument("--lookback-days", type=int, default=1095)
    parser.add_argument("--mode", choices=["history", "statistics", "extras"], default="history")
    parser.add_argument("--targeted-statistics", action="store_true",
                        help="Queue only identifiable missing fields whose retry is due, recent years first")
    parser.add_argument("--target-tour", choices=("atp", "wta"), default=None,
                        help="Limit statistics candidates to the selected tour; never affects history mode")
    parser.add_argument("--max-requests", type=int, default=4000)
    parser.add_argument("--history-dir", default=str(ROOT / ".cache/tbt/history"))
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", ""))
    parser.add_argument("--release-tag", default="tbt-data-v1")
    parser.add_argument("--publish", action="store_true", help="Download/publish via gh; use the supplied serialized workflow")
    args = parser.parse_args()
    if args.targeted_statistics and args.mode != "statistics":
        parser.error("--targeted-statistics requires statistics mode")
    if args.target_tour and (args.mode != "statistics" or not args.targeted_statistics):
        parser.error("--target-tour requires targeted statistics mode")
    high_yield_setting = os.environ.get("BLINQ_AUTOFILL_HIGH_YIELD", "false").lower()
    if high_yield_setting not in ("true", "false"):
        parser.error("BLINQ_AUTOFILL_HIGH_YIELD must be true or false")
    if high_yield_setting == "true" and (args.mode != "statistics" or not args.targeted_statistics):
        parser.error("High-yield priority requires targeted statistics mode")
    try:
        start, end = history_window(args.start, args.end, args.lookback_days)
    except ValueError as exc:
        parser.error(str(exc))
    if not 1 <= args.max_requests <= 12000:
        parser.error("max-requests must be 1..12000")
    if not settings.rapidapi_key:
        parser.error("Set RAPIDAPI_KEY before starting")
    if settings.rapidapi_host != "tennisapi1.p.rapidapi.com" or settings.rapidapi_base_url != "https://tennisapi1.p.rapidapi.com":
        parser.error("Downloader requires the subscribed tennisapi1 host and HTTPS base URL")
    directory = Path(args.history_dir)
    directory.mkdir(parents=True, exist_ok=True)
    store = None
    if args.publish:
        store = ReleaseStore(args.data_repository, args.release_tag, directory)
        store.download()
    # The operator-supplied --max-requests value is the only local request cap.
    # No rolling reservation ledger is used for history/statistics downloads.
    allocation = args.max_requests
    rows = load_partitions(directory) if list(directory.glob("history-*.parquet")) else []
    matches, history_safety = sanitize_history_identities(rows)
    if history_safety.get("changed"):
        print(json.dumps({"history_safety": history_safety}, ensure_ascii=False), flush=True)
        limit = quarantine_budget(len(rows))
        if int(history_safety.get("quarantined_rows") or 0) > limit:
            raise ValueError(
                f"History identity corruption exceeds automatic safety budget {limit}; "
                "run mode=history-repair for diagnostics"
            )
        # Persist the deterministic safety cleanup before spending provider calls.
        # This removes legacy duplicate identity corruption from the private release
        # and makes the run resumable even if the provider budget is later exhausted.
        if store:
            repaired_paths = []
            repaired_removals = []
            for year in history_safety.get("affected_years", []):
                path, was_removed = sync_year_partition(
                    matches, directory, int(year),
                    extra_manifest={"identity_safety_repair": "automatic"},
                )
                if path is not None:
                    repaired_paths.append(path)
                elif was_removed:
                    repaired_removals.append(f"history-{int(year):04d}.parquet")
            manifest_file = directory / "history_manifest.json"
            if manifest_file.is_file():
                repaired_paths.append(manifest_file)
            safety_report = directory / "history_identity_safety_report.json"
            write_json(safety_report, history_safety)
            repaired_paths.append(safety_report)
            store.upload_bundle(repaired_paths, remove_names=repaired_removals)
    progress_file = directory / "download_progress.json"
    progress = read_json(progress_file, {"schema": 1, "completed_days": []})
    if progress.get("schema") != 1:
        raise ValueError("Unsupported download progress schema")

    # Recovery guard: an interrupted/partial release upload can leave
    # download_progress.json ahead of the physical yearly parquet.
    if args.mode == "history":
        existing_years = set()
        for part in directory.glob("history-*.parquet"):
            try:
                existing_years.add(int(part.stem.split("-")[-1]))
            except (TypeError, ValueError):
                continue
        recovery = reopen_history_gap_days(matches, progress, start, end, existing_years)
        reopened_days = recovery.pop("reopened_days")
        if reopened_days:
            progress["recovery_reset"] = {
                "at": datetime.now(timezone.utc).isoformat(),
                **recovery,
                "reopened_day_count": len(reopened_days),
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
            }
            write_json(progress_file, progress)
            print(json.dumps({
                "warning": "completed_days_reopened_for_history_gap_recovery",
                **recovery,
                "reopened_day_count": len(reopened_days),
            }), flush=True)

    pending_years = set()
    pending_removals = set()

    def checkpoint(years, publish=False):
        pending_years.update(years)
        for year in sorted(years):
            path, was_removed = sync_year_partition(
                matches,
                directory,
                year,
                extra_manifest={"coverage_status": "incremental_download"},
            )
            asset_name = f"history-{int(year):04d}.parquet"
            if path is not None:
                pending_removals.discard(asset_name)
            elif was_removed:
                pending_removals.add(asset_name)
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(progress_file, progress)
        if publish and store:
            bundle = [
                directory / f"history-{y}.parquet"
                for y in sorted(pending_years)
                if (directory / f"history-{y}.parquet").is_file()
            ]
            manifest_file = directory / "history_manifest.json"
            if manifest_file.is_file():
                bundle.append(manifest_file)
            bundle.append(progress_file)
            removals = sorted(
                name
                for name in pending_removals
                if not (directory / name).is_file()
            )
            if removals:
                store.upload_bundle(bundle, remove_names=removals)
            else:
                store.upload_bundle(bundle)
            pending_years.clear()
            pending_removals.clear()

    provider = RapidTennisClient(request_budget=None)
    provider.request_limit = allocation
    report = Counter()
    statistics_value = Counter()
    statistics_segments = {}
    statistics_adaptive_queue = None
    statistics_unavailable_reasons = Counter()
    expected_statistics = {}
    expected_per_set = {}
    statistics_changed_years = set()
    extras_expected = {}
    extras_changed_years = set()
    extras_processed_by_year = Counter()
    provider_quarantine = []
    enricher = None
    primary_error = None
    primary_traceback = None
    secondary_errors = []
    try:
        if args.mode == "history":
            download_days(provider, matches, progress, start, end, checkpoint, provider_quarantine)
        elif args.mode == "extras":
            changed = set()
            pending = _extras_candidates(matches, start, end)
            report["extras_candidate_rows"] = len(pending)
            report["extras_candidate_rows_by_year"] = dict(Counter(
                str(m.scheduled_at.year) for m in pending
            ))
            report["extras_priority_policy"] = "newest_season_first_then_verified_identity"
            report["extras_first_100_by_year"] = dict(Counter(
                str(m.scheduled_at.year) for m in pending[:100]
            ))
            for index, match in enumerate(pending, 1):
                before = dict(match.provider_payload or {})
                before_calls = provider.request_count
                try:
                    outcome = enrich_event_extras(match, provider)
                    report["extras_" + outcome["status"]] += 1
                    if outcome["status"] == "processed":
                        extras_processed_by_year[str(match.scheduled_at.year)] += 1
                    for field in ("markets", "pbp"):
                        report[f"extras_{field}_{outcome[field]}"] += 1
                except RequestBudgetExceeded:
                    # Reaching the allocated API cap is a normal checkpoint stop,
                    # not a rejected provider event. The outer handler saves progress.
                    raise
                except ProviderError as exc:
                    report["extras_rejected"] += 1
                    print(json.dumps({"extras_rejected_match_id": str(match.match_id),
                                      "reason_type": type(exc).__name__}), flush=True)
                    if report["extras_rejected"] >= 25:
                        raise RuntimeError("Too many rejected extras events; fail closed") from exc
                finally:
                    if (match.provider_payload or {}) != before:
                        year = match.scheduled_at.year
                        changed.add(year)
                        pending_years.add(year)
                        extras_changed_years.add(year)
                        raw = match.provider_payload or {}
                        observed = {key: raw[key] for key in
                                    ("_tbt_tennisapi_markets", "_tbt_tennisapi_pbp")
                                    if key in raw and before.get(key) != raw[key]}
                        if observed:
                            extras_expected[str(match.match_id)] = observed
                    report["extras_requests"] += provider.request_count - before_calls
                if index % 40 == 0:
                    checkpoint(changed, True)
                    changed.clear()
            checkpoint(changed, True)
        else:
            enricher = StatisticsEnricher(provider, directory / "statistics_cache.sqlite",
                                         targeted=args.targeted_statistics)
            changed = set()
            statistics_candidates, statistics_plan = _statistics_candidates(
                matches, start, end, targeted=args.targeted_statistics,
                historical_high_yield=high_yield_setting == "true",
                target_tour=args.target_tour)
            write_json(directory / "statistics_gap_plan.json", statistics_plan)
            report["statistics_candidate_rows"] = int(statistics_plan["candidate_rows"])
            report["statistics_already_quality_ready"] = int(statistics_plan["already_quality_ready"])
            # Only the scheduled hourly high-yield mode self-tunes; manual
            # statistics requests retain their existing deterministic order.
            if args.targeted_statistics and high_yield_setting == "true":
                statistics_adaptive_queue = AdaptiveStatisticsQueue(
                    statistics_candidates, statistics_plan["bucket_coverage"])
                statistics_plan["online_adaptive_priority"] = True
            print(json.dumps({"statistics_gap_plan": statistics_plan}, ensure_ascii=False), flush=True)
            processed = 0
            for match in (statistics_adaptive_queue if statistics_adaptive_queue is not None
                          else statistics_candidates):
                processed += 1
                stats_before = dict(match.stats or {})
                per_set_before = (match.provider_payload or {}).get("_tbt_statistics_by_set")
                requests_before = provider.request_count
                status = enricher.enrich(match)
                per_set_after = (match.provider_payload or {}).get("_tbt_statistics_by_set")
                if args.targeted_statistics and per_set_after and per_set_before != per_set_after:
                    expected_per_set[str(match.match_id)] = per_set_after
                value_change = statistics_value_change(stats_before, match.stats)
                if args.targeted_statistics and value_change["new_statistic_values"]:
                    expected_statistics[str(match.match_id)] = {
                        key: value for key, value in match.stats.items()
                        if value is not None and stats_before.get(key) is None
                    }
                statistics_value.update(value_change)
                source = "api" if provider.request_count > requests_before else "local_or_cache"
                statistics_value[source + "_new_quality_ready_rows"] += value_change["new_quality_ready_rows"]
                statistics_value[source + "_new_statistic_values"] += value_change["new_statistic_values"]
                if args.targeted_statistics:
                    _record_targeted_statistics_outcome(
                        statistics_segments, statistics_unavailable_reasons,
                        match, status, provider.request_count - requests_before, value_change,
                    )
                    if statistics_adaptive_queue is not None:
                        statistics_adaptive_queue.record(
                            match, provider.request_count - requests_before, value_change)
                report[status] += 1
                if status in {"enriched", "unavailable", "conflict"}:
                    statistics_changed_years.add(match.scheduled_at.year)
                    changed.add(match.scheduled_at.year)
                    pending_years.add(match.scheduled_at.year)
                    if processed % (250 if args.targeted_statistics else 50) == 0:
                        checkpoint(changed, True)
                        changed.clear()
            checkpoint(changed, True)
    except RequestBudgetExceeded as exc:
        report["budget_stopped"] = 1
        print(str(exc), flush=True)
    except Exception as exc:
        # Preserve the real provider/parser failure even if best-effort
        # checkpoint/report/cleanup work also fails. Secondary failures are
        # chained/noted below but must never replace the primary cause.
        primary_error = exc
        primary_traceback = exc.__traceback__
    finally:
        try:
            # Includes partial statistics/history batches on a budget stop
            # or parser/provider error.
            checkpoint(set(pending_years), True)
        except Exception as exc:
            report["checkpoint_failed"] = 1
            secondary_errors.append(("final checkpoint", exc))

        report["requests_including_retries"] = provider.request_count
        report["stored_matches"] = len(matches)
        report["completed_days"] = len(progress["completed_days"])
        report["allocated_requests"] = allocation
        if provider_quarantine:
            report["provider_identity_quarantined"] = len(provider_quarantine)
        try:
            output_report = dict(report)
            if args.mode == "statistics":
                requests = provider.request_count
                output_report["statistics_data_value"] = {
                    **dict(statistics_value),
                    "api_quality_ready_rows_per_1000_requests": (
                        1000 * statistics_value["api_new_quality_ready_rows"] / requests if requests else None
                    ),
                    "api_new_statistic_values_per_1000_requests": (
                        1000 * statistics_value["api_new_statistic_values"] / requests if requests else None
                    ),
                    "policy": "Actual full serve+return readiness transitions; cache/local gains separated. Denominator includes provider retries/failures. Not an estimate of model accuracy gain.",
                }
            if args.mode == "extras":
                output_report["extras_observed_matches"] = len(extras_expected)
                output_report["extras_processed_by_year"] = dict(extras_processed_by_year)
                output_report["extras_coverage_policy"] = (
                    "Post-match research only. Opening/latest lack as-of timestamps; "
                    "PBP is structural, not model features."
                )
            if args.targeted_statistics:
                if statistics_adaptive_queue is not None:
                    output_report["statistics_adaptive_priority"] = statistics_adaptive_queue.summary()
                output_report["statistics_segment_yield"] = _statistics_segment_yield(statistics_segments)
                output_report["statistics_unavailable_reasons"] = dict(statistics_unavailable_reasons)
                output_report["statistics_segment_yield_policy"] = (
                    "Tour/year diagnostic only; per-match API request deltas include detail "
                    "lookups and retries; local/cache gains are separate; no extra API calls."
                )
            write_json(directory / "download_report.json", output_report)
            if args.targeted_statistics:
                write_json(directory / "statistics_expected.json", {
                    "years": sorted(statistics_changed_years),
                    "added_fields": expected_statistics,
                    "per_set_markers": expected_per_set,
                })
            if args.mode == "extras":
                write_json(directory / "extras_expected.json", {
                    "years": sorted(extras_changed_years), "markers": extras_expected,
                })
            print(json.dumps(output_report, indent=2), flush=True)
        except Exception as exc:
            secondary_errors.append(("download report", exc))

        try:
            if provider_quarantine:
                quarantine_path = directory / "history_provider_quarantine.json"
                write_json(quarantine_path, {
                    "schema": 1,
                    "count": len(provider_quarantine),
                    "rows": provider_quarantine,
                    "policy": "skip ambiguous incoming provider identities; preserve canonical history",
                })
                if store:
                    store.upload_bundle([quarantine_path])
        except Exception as exc:
            secondary_errors.append(("provider quarantine report", exc))

        try:
            provider.client.close()
        except Exception as exc:
            secondary_errors.append(("provider cleanup", exc))
        if enricher:
            try:
                enricher.close()
            except Exception as exc:
                secondary_errors.append(("statistics cleanup", exc))

    if primary_error is not None:
        for label, error in secondary_errors:
            try:
                primary_error.add_note(f"Secondary {label} failure: {error!r}")
            except AttributeError:
                pass
        cause = secondary_errors[0][1] if secondary_errors else None
        if cause is not None:
            raise primary_error.with_traceback(primary_traceback) from cause
        raise primary_error.with_traceback(primary_traceback)

    if secondary_errors:
        label, first_error = secondary_errors[0]
        for extra_label, error in secondary_errors[1:]:
            try:
                first_error.add_note(f"Secondary {extra_label} failure: {error!r}")
            except AttributeError:
                pass
        raise first_error


if __name__ == "__main__":
    main()
