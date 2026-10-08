"""Read-only eligibility audit for historical market features.

Input: JSONL records, each containing event_id, scheduled_at, observed_at,
market, selection, and optionally line. Never writes canonical partitions.
Missing or invalid timestamps are rejected, not imputed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def eligibility(record):
    if not isinstance(record, dict) or not str(record.get("event_id") or "").strip():
        return "reject_missing_identity"
    start = parse_utc(record.get("scheduled_at"))
    seen = parse_utc(record.get("observed_at"))
    if start is None or seen is None:
        return "reject_unverified_timestamp"
    if seen >= start:
        return "reject_not_prematch"
    market = str(record.get("market") or "").lower()
    if market in {"handicap", "spread", "total", "totals"}:
        if record.get("line") is None:
            return "reject_missing_line"
        if parse_utc(record.get("line_observed_at")) is None:
            return "reject_unverified_line_timestamp"
        if parse_utc(record["line_observed_at"]) >= start:
            return "reject_line_not_prematch"
    return "eligible_research_only"


def audit(path):
    counts = Counter()
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                counts["reject_invalid_json"] += 1
                continue
            counts[eligibility(record)] += 1
    return {"schema": 1, "mode": "read_only", "canonical_writes": 0,
            "counts": dict(sorted(counts.items())),
            "production_eligible": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.input), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
