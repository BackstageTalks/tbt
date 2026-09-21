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


from release_store import ReleaseStore
from date_window import history_window


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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None, help="Optional oldest date; overrides lookback")
    parser.add_argument("--end", default=None, help="Optional newest date; default yesterday UTC")
    parser.add_argument("--lookback-days", type=int, default=1095)
    parser.add_argument("--mode", choices=["history", "statistics"], default="history")
    parser.add_argument("--max-requests", type=int, default=4000)
    parser.add_argument("--history-dir", default=str(ROOT / ".cache/tbt/history"))
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", ""))
    parser.add_argument("--release-tag", default="tbt-data-v1")
    parser.add_argument("--publish", action="store_true", help="Download/publish via gh; use the supplied serialized workflow")
    args = parser.parse_args()
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
    provider_quarantine = []
    enricher = None
    primary_error = None
    primary_traceback = None
    secondary_errors = []
    try:
        if args.mode == "history":
            download_days(provider, matches, progress, start, end, checkpoint, provider_quarantine)
        else:
            enricher = StatisticsEnricher(provider, directory / "statistics_cache.sqlite")
            changed = set()
            for match in sorted(matches, key=lambda m: m.scheduled_at, reverse=True):
                if not start <= match.scheduled_at.date() <= end:
                    continue
                status = enricher.enrich(match)
                report[status] += 1
                if status in {"enriched", "unavailable"}:
                    changed.add(match.scheduled_at.year)
                    pending_years.add(match.scheduled_at.year)
                    if sum(report.values()) % 50 == 0:
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
            write_json(directory / "download_report.json", dict(report))
            print(json.dumps(dict(report), indent=2), flush=True)
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
