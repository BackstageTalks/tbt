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
from tbt.data.history_snapshot import load_partitions, merge_matches, write_year_partition
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


def _merge_completed_rows(matches, completed_rows):
    current = list(matches.values()) if isinstance(matches, dict) else list(matches)
    merged = merge_matches(current, completed_rows)
    ids = [str(match.match_id) for match in merged]
    if len(ids) != len(set(ids)):
        raise ValueError(
            "Ambiguous match identity collision; refusing to checkpoint history"
        )
    if isinstance(matches, dict):
        matches.clear()
        matches.update({match.match_id: match for match in merged})
    else:
        matches[:] = merged


def download_days(provider, matches, progress, start, end, checkpoint):
    """Newest first. Mark a day complete only after BOTH tours succeed."""
    done = set(progress.get("completed_days", []))
    day = end
    count = 0
    while day >= start:
        if day.isoformat() not in done:
            rows = []
            for tour in ("atp", "wta"):
                rows.extend(provider.matches_for_day(tour, day, historical=True))
            completed_rows = [match for match in rows if match.is_completed]
            if completed_rows:
                _merge_completed_rows(matches, completed_rows)
            done.add(day.isoformat())
            progress["completed_days"] = sorted(done)
            count += 1
            checkpoint({day.year}, count % 7 == 0)
            print(json.dumps({"completed_day": day.isoformat(), "rows": len(rows),
                              "requests": provider.request_count}), flush=True)
        day -= timedelta(days=1)


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
    matches = list(rows)
    progress_file = directory / "download_progress.json"
    progress = read_json(progress_file, {"schema": 1, "completed_days": []})
    if progress.get("schema") != 1:
        raise ValueError("Unsupported download progress schema")
    pending_years = set()

    def checkpoint(years, publish=False):
        pending_years.update(years)
        for year in years:
            if any(m.scheduled_at.year == year for m in matches):
                write_year_partition(matches, directory, year,
                    extra_manifest={"coverage_status": "incremental_download"})
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
            store.upload_bundle(bundle)
            pending_years.clear()

    provider = RapidTennisClient(request_budget=None)
    provider.request_limit = allocation
    report = Counter()
    enricher = None
    try:
        if args.mode == "history":
            download_days(provider, matches, progress, start, end, checkpoint)
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
    finally:
        checkpoint_error = None
        try:
            # Includes partial statistics/history batches on a budget stop
            # or parser/provider error.
            checkpoint(set(pending_years), True)
        except Exception as exc:
            checkpoint_error = exc
            report["checkpoint_failed"] = 1
        finally:
            report["requests_including_retries"] = provider.request_count
            report["stored_matches"] = len(matches)
            report["completed_days"] = len(progress["completed_days"])
            report["allocated_requests"] = allocation
            try:
                write_json(directory / "download_report.json", dict(report))
                print(json.dumps(dict(report), indent=2), flush=True)
            finally:
                try:
                    provider.client.close()
                finally:
                    if enricher:
                        enricher.close()

        if checkpoint_error is not None:
            raise checkpoint_error


if __name__ == "__main__":
    main()
