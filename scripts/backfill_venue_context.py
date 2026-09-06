"""Backfill compact venue/city/country context from TennisApi into existing history."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from date_window import history_window
from download_tennis_history import read_json, write_json, merge_match
from history_download_budget import LocalRequestBudget, reserve_allocation
from release_store import ReleaseStore
from tbt.config import settings
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.weather_archive import explicit_location


def _provider_event_id(match):
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
        "id",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    value = event.get("id")
    return str(value) if value not in (None, "") else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--lookback-days", type=int, default=1095)
    parser.add_argument("--max-requests", type=int, default=4000)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    args = parser.parse_args()

    try:
        start, end = history_window(args.start, args.end, args.lookback_days)
    except ValueError as exc:
        parser.error(str(exc))

    if not 1 <= args.max_requests <= 12000:
        parser.error("max-requests must be 1..12000")
    if not settings.rapidapi_key:
        parser.error("Set RAPIDAPI_KEY before starting")
    if (
        settings.rapidapi_host != "tennisapi1.p.rapidapi.com"
        or settings.rapidapi_base_url != "https://tennisapi1.p.rapidapi.com"
    ):
        parser.error("Venue backfill requires the subscribed tennisapi1 host")

    directory = ROOT / ".cache/tbt/venue-backfill"
    store = ReleaseStore(args.data_repository, "tbt-data-v1", directory)
    store.download(extra_names=("venue_backfill_progress.json",))

    matches = {
        match.match_id: match
        for match in load_partitions(directory)
    }

    provider_index = {}
    for key, match in matches.items():
        provider_id = _provider_event_id(match)
        if provider_id:
            provider_index[provider_id] = key

    progress_file = directory / "venue_backfill_progress.json"
    progress = read_json(
        progress_file,
        {"schema": 1, "completed_days": []},
    )
    if progress.get("schema") != 1:
        raise ValueError("Unsupported venue backfill progress schema")

    budget_file = directory / "request_budget.json"
    ledger, allocation = reserve_allocation(
        read_json(budget_file, {}),
        args.max_requests,
        run_id=(
            os.getenv("GITHUB_RUN_ID", "manual")
            + "-"
            + os.getenv("GITHUB_RUN_ATTEMPT", "1")
            + "-venue"
        ),
        purpose="history",
    )
    if not allocation:
        print("No TennisApi allowance available. Existing reservations are retained.")
        return
    write_json(budget_file, ledger)
    store.upload_bundle([budget_file])

    report = Counter()
    changed_years = set()
    pending_years = set()

    def checkpoint(*, publish=True):
        for year in sorted(changed_years):
            write_year_partition(
                matches.values(),
                directory,
                year,
                extra_manifest={
                    "coverage_status": "venue_context_backfill",
                },
            )
            pending_years.add(year)

        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(progress_file, progress)

        if publish:
            paths = [
                directory / f"history-{year}.parquet"
                for year in sorted(pending_years)
            ]
            if pending_years:
                paths.append(directory / "history_manifest.json")
            paths.append(progress_file)
            store.upload_bundle(paths)
            pending_years.clear()

        changed_years.clear()

    # Only spend provider calls on days that actually contain missing locations.
    needed_days = sorted(
        {
            match.scheduled_at.astimezone(timezone.utc).date()
            for match in matches.values()
            if start <= match.scheduled_at.astimezone(timezone.utc).date() <= end
            and explicit_location(match) is None
        },
        reverse=True,
    )

    done = set(progress.get("completed_days", []))
    needed_days = [
        day for day in needed_days
        if day.isoformat() not in done
    ]

    local_budget = LocalRequestBudget(
        directory / "venue_request_budget.sqlite"
    )
    provider = RapidTennisClient(request_budget=local_budget)
    provider.request_limit = allocation

    processed_since_checkpoint = 0

    try:
        for day in needed_days:
            rows = []
            # Both tours must finish before this day is considered complete.
            for tour in ("atp", "wta"):
                rows.extend(
                    provider.matches_for_day(
                        tour,
                        day,
                        historical=True,
                    )
                )

            report["provider_matches_seen"] += len(rows)
            day_updates = 0

            for incoming in rows:
                provider_id = _provider_event_id(incoming)
                existing_key = (
                    provider_index.get(provider_id)
                    if provider_id
                    else None
                )

                if existing_key is None and incoming.match_id in matches:
                    existing_key = incoming.match_id

                if existing_key is None:
                    report["provider_rows_not_in_history"] += 1
                    continue

                existing = matches[existing_key]
                before = explicit_location(existing)

                merged = merge_match(existing, incoming)
                # Venue enrichment must never silently mutate our stable historical id.
                if merged.match_id != existing.match_id:
                    merged = replace(merged, match_id=existing.match_id)

                matches[existing_key] = merged
                after = explicit_location(merged)

                if before is None and after is not None:
                    report["locations_added"] += 1
                    day_updates += 1
                elif before is None:
                    report["still_missing_after_provider_refetch"] += 1

                merged_provider_id = _provider_event_id(merged)
                if merged_provider_id:
                    provider_index[merged_provider_id] = existing_key

            if day_updates:
                changed_years.add(day.year)

            done.add(day.isoformat())
            progress["completed_days"] = sorted(done)
            report["completed_days_this_run"] += 1
            processed_since_checkpoint += 1

            print(
                json.dumps(
                    {
                        "venue_day": day.isoformat(),
                        "provider_rows": len(rows),
                        "locations_added": day_updates,
                        "requests": provider.request_count,
                    }
                ),
                flush=True,
            )

            if processed_since_checkpoint >= 7:
                checkpoint()
                processed_since_checkpoint = 0

    except RequestBudgetExceeded as exc:
        report["budget_stopped"] = 1
        print(str(exc), flush=True)
    finally:
        try:
            checkpoint()
        finally:
            try:
                provider.client.close()
            finally:
                local_budget.close()

    remaining = sum(
        1
        for match in matches.values()
        if start <= match.scheduled_at.astimezone(timezone.utc).date() <= end
        and explicit_location(match) is None
    )

    report["remaining_matches_without_explicit_location"] = remaining
    report["requests_including_retries"] = provider.request_count
    report["allocated_requests"] = allocation
    report["days_remaining_unscanned"] = max(
        0,
        len(needed_days) - int(report["completed_days_this_run"]),
    )

    report_path = directory / "venue_backfill_report.json"
    write_json(report_path, dict(report))
    store.upload_bundle([report_path])

    print(json.dumps(dict(report), indent=2), flush=True)


if __name__ == "__main__":
    main()
