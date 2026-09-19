"""Backfill and maintain a separate doubles history release.

The canonical singles history remains untouched.  This collector reads raw daily
provider events, keeps completed non-mixed doubles only, and stores compact pair
/member identities for the isolated doubles model.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from history_download_budget import LocalRequestBudget
from release_store import ReleaseStore
from tbt.config import settings
from tbt.providers.rapidapi import RapidTennisClient, RequestBudgetExceeded
from tbt.services.doubles_selection import compact_history_row, history_report, merge_history

HISTORY_ASSET = "doubles_history.json"
REPORT_ASSET = "doubles_history_report.json"


def _load(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect isolated historical doubles data")
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--max-requests", type=int, default=3000)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    args = parser.parse_args()
    if not settings.rapidapi_key:
        parser.error("RAPIDAPI_KEY is required")
    if args.lookback_days < 1:
        parser.error("lookback-days must be >= 1")
    if not 1 <= args.max_requests <= 10000:
        parser.error("max-requests must be 1..10000")

    today = datetime.now(timezone.utc).date()
    end = datetime.fromisoformat(args.end).date() if args.end else today - timedelta(days=1)
    start = datetime.fromisoformat(args.start).date() if args.start else end - timedelta(days=args.lookback_days - 1)
    if start > end:
        parser.error("start must be <= end")

    directory = ROOT / ".cache" / "tbt" / "doubles"
    directory.mkdir(parents=True, exist_ok=True)
    store = ReleaseStore(args.data_repository, "tbt-doubles-data-v1", directory)
    assets = store._asset_names()
    if HISTORY_ASSET in assets:
        store.download(extra_names=(HISTORY_ASSET,), required_names=(HISTORY_ASSET,))
    existing_payload = _load(directory / HISTORY_ASSET, {})
    existing = existing_payload.get("matches") if isinstance(existing_payload, dict) else []
    if not isinstance(existing, list):
        existing = []

    # Resume historical backfill from the oldest stored day instead of spending
    # every quota window re-downloading the newest dates. Normal refresh keeps the
    # last seven days current, so the manual doubles-data run can progress backward.
    requested_start, requested_end = start, end
    if existing and not args.start and not args.end:
        existing_days = []
        for row in existing:
            try:
                existing_days.append(datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00")).date())
            except (ValueError, TypeError):
                pass
        if existing_days:
            oldest = min(existing_days)
            if oldest > requested_start:
                end = min(end, oldest - timedelta(days=1))
            else:
                end = requested_start - timedelta(days=1)

    budget = LocalRequestBudget(directory / "local_request_budget.sqlite", duration_seconds=7200)
    client = RapidTennisClient(request_budget=budget)
    client.request_limit = args.max_requests
    collected = []
    errors = []
    day = end
    try:
        while day >= start:
            try:
                rows = client.doubles_for_day(day, historical=True)
            except RequestBudgetExceeded as exc:
                errors.append({"day": day.isoformat(), "error": str(exc), "budget_exhausted": True})
                break
            except Exception as exc:
                errors.append({"day": day.isoformat(), "error": str(exc)})
                day -= timedelta(days=1)
                continue
            collected.extend(match for match in rows if match.is_completed)
            day -= timedelta(days=1)
    finally:
        try:
            client.client.close()
        finally:
            budget.close()

    merged = merge_history(existing, collected)
    report = {
        **history_report(merged),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"requested_start": requested_start.isoformat(), "requested_end": requested_end.isoformat(), "effective_start": start.isoformat(), "effective_end": end.isoformat()},
        "requests_used": client.request_count,
        "max_requests": args.max_requests,
        "new_or_refreshed": len({compact_history_row(m)["event_id"] for m in collected}),
        "errors": errors[-20:],
    }
    payload = {"schema": 1, "generated_at": report["generated_at"], "matches": merged}
    (directory / HISTORY_ASSET).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / REPORT_ASSET).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    store.upload_bundle([directory / HISTORY_ASSET, directory / REPORT_ASSET])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
