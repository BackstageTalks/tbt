"""Audit private history parquet partitions without loading MatchRecord objects."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from release_store import ReleaseStore


NULLISH_TEXT = {"", "nan", "none", "null", "<na>", "nat"}


def clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.casefold() in NULLISH_TEXT else text


def row_preview(row: dict) -> dict:
    keep = (
        "match_id",
        "scheduled_at",
        "tour",
        "tournament",
        "tournament_id",
        "round_name",
        "player1_id",
        "player1_name",
        "player2_id",
        "player2_name",
        "winner_id",
        "status",
    )
    return {key: clean_text(row.get(key)) for key in keep}


def audit_partition(path: Path) -> tuple[dict, list[dict]]:
    frame = pd.read_parquet(path, engine="pyarrow")
    issues: list[dict] = []

    required_columns = {
        "match_id",
        "scheduled_at",
        "player1_id",
        "player2_id",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        return (
            {
                "file": path.name,
                "rows": int(len(frame)),
                "fatal": f"missing columns: {', '.join(missing_columns)}",
            },
            issues,
        )

    for idx, row in enumerate(frame.to_dict(orient="records"), start=1):
        match_id = clean_text(row.get("match_id"))
        p1 = clean_text(row.get("player1_id"))
        p2 = clean_text(row.get("player2_id"))

        row_issues = []

        if not match_id:
            row_issues.append("missing_match_id")
        if not p1:
            row_issues.append("missing_player1_id")
        if not p2:
            row_issues.append("missing_player2_id")
        if p1 and p2 and p1 == p2:
            row_issues.append("identical_player_ids")

        raw_dt = row.get("scheduled_at")
        try:
            parsed = pd.to_datetime(raw_dt, utc=True, errors="raise")
            if pd.isna(parsed):
                raise ValueError("NaT")
        except Exception:
            row_issues.append("invalid_scheduled_at")

        if row_issues:
            issues.append(
                {
                    "file": path.name,
                    "row": idx,
                    "issues": row_issues,
                    "record": row_preview(row),
                }
            )

    counts: dict[str, int] = {}
    for issue in issues:
        for kind in issue["issues"]:
            counts[kind] = counts.get(kind, 0) + 1

    return (
        {
            "file": path.name,
            "rows": int(len(frame)),
            "issue_rows": len(issues),
            "counts": counts,
        },
        issues,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=100,
        help="Maximum invalid rows printed to the log.",
    )
    args = parser.parse_args()

    directory = ROOT / ".cache/tbt/history-audit"
    store = ReleaseStore(args.data_repository, "tbt-data-v1", directory)
    store.download()

    partitions = sorted(directory.glob("history-*.parquet"))
    if not partitions:
        raise SystemExit("No history-YYYY.parquet partitions found")

    summaries = []
    all_issues = []

    for path in partitions:
        summary, issues = audit_partition(path)
        summaries.append(summary)
        all_issues.extend(issues)

    report = {
        "partitions": summaries,
        "total_rows": sum(item.get("rows", 0) for item in summaries),
        "invalid_rows": len(all_issues),
        "details": all_issues[: args.max_details],
        "details_truncated": max(0, len(all_issues) - args.max_details),
    }

    report_path = directory / "history_audit_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    if all_issues:
        raise SystemExit(
            f"History audit found {len(all_issues)} invalid row(s). "
            "See history_audit_report.json output above."
        )


if __name__ == "__main__":
    main()
