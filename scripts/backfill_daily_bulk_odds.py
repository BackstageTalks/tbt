"""Read-only research backfill of RapidAPI daily bulk odds (one call per day).

Writes gzip JSON per day to an output directory (uploaded as a workflow
artifact). No CDB writes, no production mutation. Quote time is unverified
(``historical_two_way_unspecified_timestamp``): research/backtest use only.
"""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import date, timedelta
from pathlib import Path


def days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def run(client, start: date, end: date, out: Path, max_requests: int) -> dict:
    if not 1 <= max_requests <= 1200:
        raise ValueError("max_requests must be 1..1200")
    out.mkdir(parents=True, exist_ok=True)
    client.request_limit = max_requests
    report = {"schema": 1, "start": start.isoformat(), "end": end.isoformat(),
              "cdb_writes": 0, "days": 0, "days_failed": 0, "events": 0,
              "price_kind": "historical_two_way_unspecified_timestamp"}
    for day in days(start, end):
        if report["days"] + report["days_failed"] >= max_requests:
            break
        try:
            payload = client.events_with_odds_for_status_day(day)
        except Exception as exc:  # budget halt or provider error: stop cleanly
            report["days_failed"] += 1
            report["stopped"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            break
        n = len(payload) if isinstance(payload, (dict, list)) else 0
        if isinstance(payload, dict) and isinstance(payload.get("odds"), dict):
            n = len(payload["odds"])
        with gzip.open(out / f"{day.isoformat()}.json.gz", "wt", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False)
        report["days"] += 1
        report["events"] += n
    report["requests"] = getattr(client, "request_count", None)
    (out / "_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--max-requests", type=int, default=400)
    ap.add_argument("--out", default=".cache/bulk-odds")
    a = ap.parse_args()
    from tbt.providers.rapidapi import RapidTennisClient
    report = run(RapidTennisClient(), date.fromisoformat(a.start), date.fromisoformat(a.end),
                 Path(a.out), a.max_requests)
    print(json.dumps(report))
    return 0 if report["days"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
