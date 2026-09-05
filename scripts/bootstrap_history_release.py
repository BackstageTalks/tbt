from __future__ import annotations

import argparse
import calendar
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import (
    ensure_partitions,
    load_manifest,
    load_snapshot,
    merge_matches,
    partition_path,
    update_year_manifest,
    write_year_partition,
)
from tbt.providers.rapidapi import RapidTennisClient
from tbt.schemas import MatchRecord

logger = logging.getLogger("tbt.bootstrap_history_release")
COLD_HISTORY_END = date(2025, 1, 1)




def _close_provider(provider: RapidTennisClient) -> None:
    close = getattr(provider, "close", None)
    if callable(close):
        close()
        return
    client = getattr(provider, "client", None)
    client_close = getattr(client, "close", None)
    if callable(client_close):
        client_close()

def _parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _full_month_key(range_start: date, range_end: date) -> str | None:
    if range_start.year != range_end.year or range_start.month != range_end.month:
        return None
    expected_end = date(
        range_start.year,
        range_start.month,
        calendar.monthrange(range_start.year, range_start.month)[1],
    )
    if range_start.day == 1 and range_end == expected_end:
        return f"{range_start.year:04d}-{range_start.month:02d}"
    return None


def _period(range_start: date, range_end: date):
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    range_end = min(range_end, yesterday, COLD_HISTORY_END - timedelta(days=1))
    current = date(range_start.year, range_start.month, 1)
    while current <= range_end:
        month_start = max(current, range_start)
        month_end = min(
            date(current.year, current.month, calendar.monthrange(current.year, current.month)[1]),
            range_end,
        )
        yield current.year, current.month, month_start, month_end
        current = date(current.year + (1 if current.month == 12 else 0), 1 if current.month == 12 else current.month + 1, 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch archived tennis history directly from RapidAPI into one private "
            "GitHub Release year partition. Supabase is never used."
        )
    )
    parser.add_argument("--start-date", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument(
        "--legacy-snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    range_start = _parse_date(args.start_date)
    range_end = _parse_date(args.end_date)
    if range_end < range_start:
        raise SystemExit("history range end must be >= start")
    if range_end >= COLD_HISTORY_END:
        raise SystemExit("V20.5 safety stop: direct cold bootstrap is restricted to 2024 and older")
    if range_start.year != range_end.year:
        raise SystemExit("V20.5 partition safety: each checkpoint must stay inside one calendar year")

    history_dir = Path(args.history_dir)
    ensure_partitions(history_dir, legacy_snapshot=args.legacy_snapshot)
    year = range_start.year
    year_path = partition_path(history_dir, year)
    existing = load_snapshot(year_path) if year_path.is_file() else []

    manifest = load_manifest(history_dir)
    year_meta = (manifest.get("years") or {}).get(str(year), {})
    completed_months = {
        str(value)
        for value in (year_meta.get("completed_provider_months") or [])
        if value
    }
    month_key = _full_month_key(range_start, range_end)
    if month_key and month_key in completed_months and not args.force:
        print(json.dumps({
            "mode": "provider-direct-cold-partition",
            "supabase_used": False,
            "skipped": True,
            "month": month_key,
            "year_asset": year_path.name,
        }, indent=2))
        return

    provider = RapidTennisClient()
    fetched_all: list[MatchRecord] = []
    report: dict[str, Any] = {
        "mode": "provider-direct-cold-partition",
        "supabase_used": False,
        "start": range_start.isoformat(),
        "end": range_end.isoformat(),
        "year": year,
        "existing_year_rows": len(existing),
        "months": {},
    }
    try:
        for y, month, month_start, month_end in _period(range_start, range_end):
            key = f"{y:04d}-{month:02d}"
            month_matches: list[MatchRecord] = []
            month_report: dict[str, int] = {"atp": 0, "wta": 0, "canonical": 0}
            for tour in ("atp", "wta"):
                logger.info("Direct GH fetch %s %s -> %s", tour.upper(), month_start, month_end)
                fetched = provider.historical_period(tour, month_start, month_end)
                completed = [match for match in fetched if match.is_completed and match.winner_id]
                month_report[tour] = len(completed)
                month_matches.extend(completed)
            month_matches = merge_matches(month_matches)
            month_report["canonical"] = len(month_matches)
            fetched_all.extend(month_matches)
            report["months"][key] = month_report
    finally:
        report["rapidapi_requests"] = getattr(provider, "request_count", None)
        report["rapidapi_remaining"] = getattr(provider, "rate_limit_remaining", None)
        report["rapidapi_limit"] = getattr(provider, "rate_limit_limit", None)
        _close_provider(provider)

    combined = merge_matches(existing, fetched_all)
    if month_key:
        completed_months.add(month_key)
    partition_meta = write_year_partition(
        combined,
        history_dir,
        year,
        extra_manifest={
            "coverage_status": "provider_backfill_in_progress",
            "completed_provider_months": sorted(completed_months),
            "last_direct_provider_backfill": {
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
                "rows_fetched": len(fetched_all),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )
    report["year_rows"] = partition_meta["rows"]
    report["year_sha256"] = partition_meta["sha256"]
    report["year_asset"] = year_path.name
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
