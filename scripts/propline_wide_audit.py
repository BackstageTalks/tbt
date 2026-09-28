#!/usr/bin/env python3
"""One-off read-only PropLine coverage audit against the current BlinQ feed.

Uses the existing PROPL secret, never calls Tennis RapidAPI, never publishes
predictions and stops before the provider's daily remaining quota reaches 150.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from release_store import ReleaseStore
from tbt.services.propline_live import (
    MAX_EVENTS_PER_REFRESH, MIN_PROVIDER_REMAINING, PropLineClient,
    discover_propline_fallback,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-events", type=int, default=75)
    args = parser.parse_args()
    if not 1 <= args.max_events <= MAX_EVENTS_PER_REFRESH:
        parser.error("max-events must be 1..75")
    key = os.getenv("PROPL", "").strip()
    if not key:
        raise RuntimeError("PROPL secret is missing")
    repository = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
    output = Path("reports/propline_wide_market_audit.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = Path(".cache/tbt/propline_wide_audit")
    store = ReleaseStore(repository, "tbt-predictions-v1", folder)
    store.download(extra_names=("feed.json",), required_names=("feed.json",))
    feed = json.loads((folder / "feed.json").read_text(encoding="utf-8"))
    if not isinstance(feed, dict) or not isinstance(feed.get("upcoming"), list):
        raise ValueError("Missing valid current upcoming predictions feed")
    now = datetime.now(timezone.utc)
    client = PropLineClient(key, max_calls=1 + 2 * args.max_events,
                            min_remaining=MIN_PROVIDER_REMAINING)
    _, report = discover_propline_fallback(
        client, feed["upcoming"], {}, now=now, max_events=args.max_events
    )
    report.update({
        "audit_at": now.isoformat(), "feed_generated_at": feed.get("generated_at"),
        "feed_upcoming_count": len(feed["upcoming"]),
        "audit_limit": args.max_events,
        "purpose": "read_only_coverage_learning_no_picks_or_ledger_changes",
        "global_quota_model": {
            "provider_claimed_daily_limit": 1000,
            "max_four_live_refreshes": 604, "clv_research_cap": 250,
            "unallocated_reserve": 146,
        },
    })
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps({"propline_wide_market_audit": report}, ensure_ascii=False),
          flush=True)
    print(f"Coverage artifact: {output}", flush=True)


if __name__ == "__main__":
    main()
