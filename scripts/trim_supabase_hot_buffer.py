from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.data.history_snapshot import load_partitions
from tbt.repositories.supabase import SupabaseRepository

CONFIRMATION = "TRIM ROLLING HOT BUFFER"


def _parse_retention_days(value: int) -> int:
    value = int(value)
    if value < 14 or value > 180:
        raise SystemExit("--retention-days must be between 14 and 180")
    return value


def _candidate_rows(repo: SupabaseRepository, cutoff: datetime) -> list[dict[str, Any]]:
    return repo.select_all(
        "matches",
        filters={"scheduled_at": f"lt.{cutoff.isoformat()}"},
        select="match_id,scheduled_at,winner_id",
        order="scheduled_at.asc",
        page_size=1000,
    )


def _delete_before(repo: SupabaseRepository, cutoff: datetime) -> None:
    response = repo.client.delete(
        f"{repo.base}/matches",
        headers=repo._headers(write=True, prefer="return=minimal"),
        params={"scheduled_at": f"lt.{cutoff.isoformat()}"},
    )
    repo._raise(response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Keep Supabase as a rolling operational hot buffer. Before deletion, "
            "verify that every completed candidate already exists in the local GH history partitions."
        )
    )
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument("--retention-days", type=int, default=60)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()

    retention_days = _parse_retention_days(args.retention_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    repo = SupabaseRepository()
    candidates = _candidate_rows(repo, cutoff)

    completed_ids = {
        str(row.get("match_id"))
        for row in candidates
        if row.get("match_id") and row.get("winner_id")
    }

    archived_ids: set[str] = set()
    if completed_ids:
        history_dir = Path(args.history_dir)
        history = load_partitions(history_dir, before=cutoff)
        archived_ids = {str(match.match_id) for match in history}

    missing = sorted(completed_ids - archived_ids)
    report: dict[str, Any] = {
        "mode": "execute" if args.execute else "preview",
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "candidate_rows": len(candidates),
        "completed_candidates": len(completed_ids),
        "completed_archived": len(completed_ids & archived_ids),
        "completed_missing_from_archive": len(missing),
        "missing_examples": missing[:20],
        "year_independent": True,
    }

    if missing:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(
            "Refusing trim: completed Supabase rows exist outside the hot buffer but are missing from GH history."
        )

    if args.execute:
        if args.confirmation != CONFIRMATION:
            raise SystemExit(f"Refusing destructive run. Confirmation must equal: {CONFIRMATION}")
        if candidates:
            _delete_before(repo, cutoff)
        remaining = _candidate_rows(repo, cutoff)
        report["rows_remaining_before_cutoff"] = len(remaining)
        if remaining:
            print(json.dumps(report, indent=2, ensure_ascii=False))
            raise SystemExit("Rolling hot-buffer trim verification failed")

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
