from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from tbt.repositories.supabase import SupabaseRepository

CUTOFF = datetime(2025, 1, 1, tzinfo=timezone.utc)
CONFIRMATION = "DELETE PRE-2025 MATCHES"


def _exact_count(repo: SupabaseRepository, start: datetime | None, end: datetime) -> int:
    headers = repo._headers(write=False)
    headers["Prefer"] = "count=exact"
    headers["Range"] = "0-0"
    params: dict[str, str] = {"select": "match_id", "limit": "1"}
    if start is not None:
        params["scheduled_at"] = f"gte.{start.isoformat()}"
        params["and"] = f"(scheduled_at.lt.{end.isoformat()})"
    else:
        params["scheduled_at"] = f"lt.{end.isoformat()}"
    response = repo.client.get(f"{repo.base}/matches", headers=headers, params=params)
    repo._raise(response)
    content_range = response.headers.get("content-range", "")
    total = content_range.rsplit("/", 1)[-1].strip() if "/" in content_range else ""
    if not total.isdigit():
        raise RuntimeError(f"Unable to parse exact count from Content-Range: {content_range!r}")
    return int(total)


def _earliest_cold_year(repo: SupabaseRepository) -> int | None:
    rows = repo.select_all(
        "matches",
        filters={"scheduled_at": f"lt.{CUTOFF.isoformat()}"},
        select="scheduled_at",
        order="scheduled_at.asc",
        max_rows=1,
        page_size=1,
    )
    if not rows:
        return None
    value = str(rows[0].get("scheduled_at") or "")
    if len(value) < 4 or not value[:4].isdigit():
        raise RuntimeError(f"Invalid earliest scheduled_at: {value!r}")
    return int(value[:4])


def _delete_range_minimal(repo: SupabaseRepository, start: datetime, end: datetime) -> None:
    response = repo.client.delete(
        f"{repo.base}/matches",
        headers=repo._headers(write=True, prefer="return=minimal"),
        params={
            "scheduled_at": f"gte.{start.isoformat()}",
            "and": f"(scheduled_at.lt.{end.isoformat()})",
        },
    )
    repo._raise(response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or delete Supabase cold-tier matches before 2025-01-01. "
            "DELETE uses return=minimal to avoid sending deleted rows back as egress."
        )
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args()

    if args.execute and args.confirmation != CONFIRMATION:
        raise SystemExit(f"Refusing destructive run. Confirmation must equal: {CONFIRMATION}")

    repo = SupabaseRepository()
    earliest = _earliest_cold_year(repo)
    total_before = _exact_count(repo, None, CUTOFF)
    report: dict[str, Any] = {
        "mode": "execute" if args.execute else "preview",
        "cutoff": CUTOFF.isoformat(),
        "cold_rows_before": total_before,
        "years": {},
        "delete_return_mode": "minimal",
    }

    if earliest is None or total_before == 0:
        report["cold_rows_after"] = 0
        print(json.dumps(report, indent=2))
        return

    for year in range(earliest, 2025):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        before = _exact_count(repo, start, end)
        entry: dict[str, Any] = {"rows_before": before}
        if args.execute and before:
            _delete_range_minimal(repo, start, end)
            entry["rows_after"] = _exact_count(repo, start, end)
            if entry["rows_after"] != 0:
                raise SystemExit(
                    f"Delete verification failed for {year}: {entry['rows_after']} rows remain"
                )
        report["years"][str(year)] = entry

    total_after = _exact_count(repo, None, CUTOFF)
    report["cold_rows_after"] = total_after
    if args.execute and total_after != 0:
        raise SystemExit(f"Cold-tier delete verification failed: {total_after} rows remain")

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
