"""Audit private history parquet partitions without mutating release data."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from release_store import ReleaseStore
from repair_history_data import invalid_reason, clean_text


PROVIDER_KEYS = (
    "_tbt_provider_event_id",
    "provider_event_id",
    "event_id",
    "eventId",
    "id",
)


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


def provider_event_id(row: dict) -> str:
    raw = row.get("provider_context_json")
    if raw in (None, ""):
        return ""
    try:
        data = raw if isinstance(raw, dict) else json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    for key in PROVIDER_KEYS:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    event = data.get("event") if isinstance(data.get("event"), dict) else {}
    value = event.get("id")
    return str(value) if value not in (None, "") else ""


def audit_partition(path: Path) -> tuple[dict, list[dict], list[dict]]:
    frame = pd.read_parquet(path, engine="pyarrow")
    issues: list[dict] = []
    identities: list[dict] = []

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
            identities,
        )

    for idx, row in enumerate(frame.to_dict(orient="records"), start=1):
        reason = invalid_reason(row)
        if reason:
            issues.append(
                {
                    "file": path.name,
                    "row": idx,
                    "issues": [reason],
                    "record": row_preview(row),
                }
            )
            continue
        identities.append(
            {
                "file": path.name,
                "row": idx,
                "match_id": clean_text(row.get("match_id")),
                "provider_event_id": provider_event_id(row),
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
        identities,
    )


def _duplicate_details(identities: list[dict], field: str, reason: str) -> list[dict]:
    grouped = defaultdict(list)
    for item in identities:
        value = item.get(field)
        if value:
            grouped[str(value)].append(item)
    output = []
    for value, rows in grouped.items():
        if len(rows) < 2:
            continue
        output.append(
            {
                "reason": reason,
                "identity": value,
                "rows": rows,
            }
        )
    return output


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
        help="Maximum issue groups printed to the log.",
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
    identities = []

    for path in partitions:
        summary, issues, partition_identities = audit_partition(path)
        summaries.append(summary)
        all_issues.extend(issues)
        identities.extend(partition_identities)

    duplicate_match = _duplicate_details(
        identities, "match_id", "duplicate_match_id"
    )
    duplicate_provider = _duplicate_details(
        identities, "provider_event_id", "duplicate_provider_event_id"
    )
    duplicate_groups = duplicate_match + duplicate_provider

    report = {
        "schema": 2,
        "partitions": summaries,
        "total_rows": sum(item.get("rows", 0) for item in summaries),
        "invalid_rows": len(all_issues),
        "duplicate_match_id_groups": len(duplicate_match),
        "duplicate_provider_event_id_groups": len(duplicate_provider),
        "details": (all_issues + duplicate_groups)[: args.max_details],
        "details_truncated": max(
            0, len(all_issues) + len(duplicate_groups) - args.max_details
        ),
    }

    report_path = directory / "history_audit_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    total_problem_groups = len(all_issues) + len(duplicate_groups)
    if total_problem_groups:
        raise SystemExit(
            f"History audit found {len(all_issues)} invalid row(s) and "
            f"{len(duplicate_groups)} duplicate identity group(s). "
            "Run mode=history-repair before training/refresh."
        )


if __name__ == "__main__":
    main()
