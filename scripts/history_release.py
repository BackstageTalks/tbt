from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import (
    ensure_partitions,
    list_partition_years,
    load_manifest,
    load_snapshot,
    merge_matches,
    partition_path,
    write_manifest,
    write_year_partition,
)
from tbt.repositories.supabase import SupabaseRepository

MATCH_SELECT = ",".join(
    (
        "match_id", "tour", "scheduled_at", "player1_id", "player1_name",
        "player2_id", "player2_name", "surface", "tournament", "tournament_id",
        "tournament_level", "round_name", "player1_rank", "player2_rank",
        "winner_id", "status", "best_of", "indoor", "stats", "provider_payload", "updated_at",
    )
)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _retention_days(cli_value: int | None) -> int:
    raw = cli_value if cli_value is not None else os.getenv("TBT_HOT_RETENTION_DAYS", "60")
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = 60
    if days < 14 or days > 180:
        raise SystemExit("Hot retention must be between 14 and 180 days")
    return days


def _latest_hot_updated_at(repo: SupabaseRepository, hot_cutoff: datetime) -> str | None:
    rows = repo.select_all(
        "matches",
        filters={"winner_id": "not.is.null", "scheduled_at": f"gte.{hot_cutoff.isoformat()}"},
        select="updated_at",
        order="updated_at.desc",
        max_rows=1,
        page_size=1,
    )
    return str(rows[0].get("updated_at")) if rows and rows[0].get("updated_at") else None


def _rows_to_matches(repo: SupabaseRepository, raw_rows: list[dict[str, Any]]):
    matches = [repo._match_from_row(row) for row in raw_rows]
    return repo._hydrate_environments(matches)


def _merge_changed(history_dir: Path, changed: list, mode: str) -> None:
    by_year: dict[int, list] = {}
    for match in changed:
        year = match.scheduled_at.astimezone(timezone.utc).year
        by_year.setdefault(year, []).append(match)

    for year, matches in sorted(by_year.items()):
        path = partition_path(history_dir, year)
        existing = load_snapshot(path) if path.is_file() and path.stat().st_size > 0 else []
        merged = merge_matches(existing, matches)
        write_year_partition(
            merged,
            history_dir,
            year,
            extra_manifest={
                "coverage_status": "partitioned_history",
                "last_hot_sync_mode": mode,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally archive the rolling Supabase hot buffer into private GitHub "
            "year partitions. The cutoff is date-relative and never tied to a calendar year."
        )
    )
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument(
        "--legacy-snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    parser.add_argument("--hot-full-refresh", action="store_true")
    parser.add_argument("--overlap-minutes", type=int, default=1440)
    parser.add_argument("--retention-days", type=int, default=None)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    retention_days = _retention_days(args.retention_days)
    hot_cutoff = now - timedelta(days=retention_days)

    history_dir = Path(args.history_dir)
    ensure_partitions(history_dir, legacy_snapshot=args.legacy_snapshot)
    previous_manifest = load_manifest(history_dir)
    repo = SupabaseRepository()

    if args.hot_full_refresh:
        print(f"V20.7 sync: explicit rolling HOT refresh from {hot_cutoff.isoformat()}")
        raw_rows = repo.select_all(
            "matches",
            filters={"winner_id": "not.is.null", "scheduled_at": f"gte.{hot_cutoff.isoformat()}"},
            select=MATCH_SELECT,
            order="updated_at.asc",
            page_size=1000,
        )
        changed = _rows_to_matches(repo, raw_rows)
        _merge_changed(history_dir, changed, "rolling-full")
        source_updated_at_max = _latest_hot_updated_at(repo, hot_cutoff)
        mode = "rolling-hot-full-refresh"
    else:
        cursor = _parse_dt(previous_manifest.get("source_updated_at_max"))
        if cursor is None:
            cursor = hot_cutoff - timedelta(minutes=max(0, args.overlap_minutes))
            mode = "rolling-hot-incremental-seed"
        else:
            cursor = cursor - timedelta(minutes=max(0, args.overlap_minutes))
            mode = "rolling-hot-incremental"

        print(
            f"V20.7 sync: {mode}; scheduled_at >= {hot_cutoff.isoformat()}, "
            f"updated_at > {cursor.isoformat()}"
        )
        raw_rows = repo.select_all(
            "matches",
            filters={
                "winner_id": "not.is.null",
                "scheduled_at": f"gte.{hot_cutoff.isoformat()}",
                "updated_at": f"gt.{cursor.isoformat()}",
            },
            select=MATCH_SELECT,
            order="updated_at.asc",
            page_size=1000,
        )
        changed = _rows_to_matches(repo, raw_rows)
        _merge_changed(history_dir, changed, "incremental")
        updated_values = [str(row.get("updated_at")) for row in raw_rows if row.get("updated_at")]
        source_updated_at_max = (
            max(updated_values)
            if updated_values
            else previous_manifest.get("source_updated_at_max")
        )

    manifest = load_manifest(history_dir)
    manifest.update(
        {
            "source_updated_at_max": source_updated_at_max,
            "last_hot_sync": {
                "mode": mode,
                "changed_rows_read_from_supabase": len(raw_rows),
                "completed_at": now.isoformat(),
                "hot_cutoff": hot_cutoff.isoformat(),
                "retention_days": retention_days,
            },
            "storage_policy": {
                "supabase_mode": "rolling_hot_buffer",
                "hot_retention_days": retention_days,
                "hot_cutoff_is_dynamic": True,
                "history_store": "private GitHub Release yearly Parquet",
                "supabase_store": "lean recent/upcoming operational rows only",
                "year_independent": True,
            },
            "supabase_full_history_read": False,
        }
    )
    write_manifest(history_dir, manifest)

    print(
        json.dumps(
            {
                "mode": mode,
                "retention_days": retention_days,
                "hot_cutoff": hot_cutoff.isoformat(),
                "changed_rows_read_from_supabase": len(raw_rows),
                "source_updated_at_max": source_updated_at_max,
                "partition_years": list_partition_years(history_dir),
                "supabase_full_history_read": False,
                "year_independent": True,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
