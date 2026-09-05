from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import (
    list_partition_years,
    load_manifest,
    load_partitions,
    load_snapshot,
    merge_matches,
    partition_path,
    write_manifest,
    write_year_partition,
)


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge the existing monolithic GitHub training snapshot into yearly "
            "partitions. Supabase is never read. Safe to rerun."
        )
    )
    parser.add_argument(
        "--legacy-snapshot",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.parquet"),
    )
    parser.add_argument(
        "--legacy-meta",
        default=str(ROOT / ".cache" / "tbt" / "training_snapshot.meta.json"),
    )
    parser.add_argument(
        "--history-dir",
        default=str(ROOT / ".cache" / "tbt" / "history"),
    )
    args = parser.parse_args()

    legacy_snapshot = Path(args.legacy_snapshot)
    legacy_meta_path = Path(args.legacy_meta)
    history_dir = Path(args.history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)

    legacy = load_snapshot(legacy_snapshot)
    legacy_meta = _load_meta(legacy_meta_path)

    by_year: dict[int, list] = {}
    for match in legacy:
        year = match.scheduled_at.astimezone(timezone.utc).year
        by_year.setdefault(year, []).append(match)

    written: dict[str, Any] = {}
    for year, year_matches in sorted(by_year.items()):
        path = partition_path(history_dir, year)
        existing = load_snapshot(path) if path.is_file() and path.stat().st_size > 0 else []
        merged = merge_matches(existing, year_matches)
        meta = write_year_partition(
            merged,
            history_dir,
            year,
            extra_manifest={
                "migration_source": legacy_snapshot.name,
                "coverage_status": (
                    "authoritative_hot_mirror"
                    if year >= 2025
                    else "legacy_snapshot_seed"
                ),
            },
        )
        written[str(year)] = {
            "legacy_rows_for_year": len(year_matches),
            "rows_after_merge": meta["rows"],
            "sha256": meta["sha256"],
        }

    manifest = load_manifest(history_dir)
    source_updated_at_max = legacy_meta.get("source_updated_at_max")
    if source_updated_at_max:
        manifest["source_updated_at_max"] = source_updated_at_max
    manifest["migration"] = {
        "source": legacy_snapshot.name,
        "legacy_rows": len(legacy),
        "legacy_file_sha256": hashlib.sha256(legacy_snapshot.read_bytes()).hexdigest(),
        "legacy_meta_sha256": legacy_meta.get("sha256"),
        "source_updated_at_max": source_updated_at_max,
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "supabase_used": False,
    }
    write_manifest(history_dir, manifest)

    partitioned = load_partitions(history_dir)
    partition_ids = {str(match.match_id) for match in partitioned}
    missing = [str(match.match_id) for match in legacy if str(match.match_id) not in partition_ids]
    if missing:
        raise SystemExit(
            f"Migration verification failed: {len(missing)} legacy match_ids missing from partitions"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "github-legacy-to-year-partitions",
                "supabase_used": False,
                "legacy_rows": len(legacy),
                "partition_rows": len(partitioned),
                "partition_years": list_partition_years(history_dir),
                "source_updated_at_max": source_updated_at_max,
                "years": written,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
