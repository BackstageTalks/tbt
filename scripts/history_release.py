from __future__ import annotations

import argparse
import json
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

HOT_TIER_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
HOT_TIER_FILTER = HOT_TIER_START.isoformat()

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


def _latest_hot_updated_at(repo: SupabaseRepository) -> str | None:
    rows = repo.select_all(
        "matches",
        filters={"winner_id": "not.is.null", "scheduled_at": f"gte.{HOT_TIER_FILTER}"},
        select="updated_at",
        order="updated_at.desc",
        max_rows=1,
        page_size=1,
    )
    return str(rows[0].get("updated_at")) if rows and rows[0].get("updated_at") else None


def _rows_to_matches(repo: SupabaseRepository, raw_rows: list[dict[str, Any]]):
    matches = [repo._match_from_row(row) for row in raw_rows]
    return repo._hydrate_environments(matches)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally mirror the lean Supabase hot tier (2025+) into private "
            "GitHub year partitions. Never reads pre-2025 history from Supabase."
        )
    )
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument(
        "--legacy-snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    parser.add_argument("--hot-full-refresh", action="store_true")
    parser.add_argument("--overlap-minutes", type=int, default=10)
    args = parser.parse_args()

    history_dir = Path(args.history_dir)
    ensure_partitions(history_dir, legacy_snapshot=args.legacy_snapshot)
    previous_manifest = load_manifest(history_dir)
    repo = SupabaseRepository()

    if args.hot_full_refresh:
        print("V20.5 sync: explicit HOT-TIER full refresh (2025+ only)")
        raw_rows = repo.select_all(
            "matches",
            filters={"winner_id": "not.is.null", "scheduled_at": f"gte.{HOT_TIER_FILTER}"},
            select=MATCH_SELECT,
            order="updated_at.asc",
            page_size=1000,
        )
        changed = _rows_to_matches(repo, raw_rows)
        by_year: dict[int, list] = {}
        for match in changed:
            by_year.setdefault(match.scheduled_at.astimezone(timezone.utc).year, []).append(match)
        for year, matches in sorted(by_year.items()):
            write_year_partition(
                merge_matches(matches),
                history_dir,
                year,
                extra_manifest={
                    "coverage_status": "authoritative_hot_mirror",
                    "last_hot_sync_mode": "full",
                },
            )
        source_updated_at_max = _latest_hot_updated_at(repo)
        mode = "hot-full-refresh"
    else:
        cursor = _parse_dt(previous_manifest.get("source_updated_at_max"))
        if cursor is None:
            cursor = HOT_TIER_START - timedelta(minutes=max(0, args.overlap_minutes))
            mode = "hot-incremental-seed"
        else:
            cursor = max(
                HOT_TIER_START,
                cursor - timedelta(minutes=max(0, args.overlap_minutes)),
            )
            mode = "hot-incremental"
        print(f"V20.5 sync: {mode} from updated_at > {cursor.isoformat()}")
        raw_rows = repo.select_all(
            "matches",
            filters={
                "winner_id": "not.is.null",
                "scheduled_at": f"gte.{HOT_TIER_FILTER}",
                "updated_at": f"gt.{cursor.isoformat()}",
            },
            select=MATCH_SELECT,
            order="updated_at.asc",
            page_size=1000,
        )
        changed = _rows_to_matches(repo, raw_rows)
        by_year: dict[int, list] = {}
        for match in changed:
            by_year.setdefault(match.scheduled_at.astimezone(timezone.utc).year, []).append(match)
        for year, matches in sorted(by_year.items()):
            path = partition_path(history_dir, year)
            existing = load_snapshot(path) if path.is_file() else []
            merged = merge_matches(existing, matches)
            write_year_partition(
                merged,
                history_dir,
                year,
                extra_manifest={
                    "coverage_status": "authoritative_hot_mirror",
                    "last_hot_sync_mode": "incremental",
                },
            )
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
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            "storage_policy": {
                "cold_history_before": "2025-01-01",
                "cold_history_store": "private GitHub Release yearly Parquet",
                "hot_history_from": "2025-01-01",
                "hot_history_store": "lean Supabase + private GitHub yearly mirror",
            },
            "supabase_full_history_read": False,
        }
    )
    write_manifest(history_dir, manifest)

    print(
        json.dumps(
            {
                "mode": mode,
                "changed_rows_read_from_supabase": len(raw_rows),
                "source_updated_at_max": source_updated_at_max,
                "partition_years": list_partition_years(history_dir),
                "supabase_full_history_read": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
