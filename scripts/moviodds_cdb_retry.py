#!/usr/bin/env python3
"""Idempotent, UTC-clock reuse for the EXISTING weekly MoviOdds CDB writer.

No GitHub cron and no CDB access: this is a pure schedule gate over the
GitHub Actions dispatch list. A previously failed/busy run is retried only
after a bounded cooldown; a successful run finishes that week's obligation.
Actual CDB mutation is performed exclusively by cdb-drive-inbox.yml.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


COOLDOWN_SECONDS = 2 * 60 * 60


def _utc(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("GitHub run timestamp without timezone")
    return moment.astimezone(timezone.utc)


def decision(runs: dict, now: datetime) -> dict:
    """Return a deterministic no-op/dispatch decision, fail closed on bad API.

    A temporary busy global writer is a completed *failure*, not a green
    import. A success (including independently verified zero new values)
    closes the current UTC week. A queued/active run prevents duplicates.
    """
    if now.tzinfo is None or not isinstance(runs, dict):
        raise ValueError("UTC scheduler input unavailable")
    now = now.astimezone(timezone.utc)
    rows = runs.get("workflow_runs")
    if not isinstance(rows, list):
        raise ValueError("GitHub Actions runs response missing workflow_runs")
    sunday = (now - timedelta(days=(now.weekday() + 1) % 7)).date()
    slot = datetime(sunday.year, sunday.month, sunday.day, 6, tzinfo=timezone.utc)
    request_id = f"moviodds-{sunday.isoformat()}"
    if now < slot:
        return {"dispatch": False, "reason": "weekly_slot_not_due", "request_id": request_id}

    title = "CDB guarded import " + request_id
    matching = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed GitHub workflow run")
        if row.get("display_title") != title:
            continue
        if row.get("event") != "workflow_dispatch" or row.get("head_branch") != "main":
            # Reject foreign runs rather than treating them as proof of success.
            continue
        timestamp = _utc(str(row.get("created_at") or ""))
        if timestamp < slot or timestamp > now + timedelta(minutes=5):
            raise ValueError("Out-of-window weekly MoviOdds run timestamp")
        matching.append((timestamp, row))

    if any(row.get("status") == "completed" and row.get("conclusion") == "success"
           for _, row in matching):
        return {"dispatch": False, "reason": "weekly_import_verified_complete",
                "request_id": request_id}
    if any(row.get("status") != "completed" for _, row in matching):
        return {"dispatch": False, "reason": "existing_attempt_active",
                "request_id": request_id}

    if matching:
        latest_at, latest = max(matching, key=lambda pair: pair[0])
        age = (now - latest_at).total_seconds()
        if age < COOLDOWN_SECONDS:
            return {"dispatch": False, "reason": "failed_attempt_cooldown",
                    "request_id": request_id}
        return {"dispatch": True, "reason": "retry_failed_or_busy_attempt",
                "request_id": request_id}
    return {"dispatch": True, "reason": "first_weekly_attempt",
            "request_id": request_id}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="Append GitHub Actions step output")
    args = parser.parse_args()
    value = json.loads(args.runs_file.read_text(encoding="utf-8"))
    result = decision(value, datetime.now(timezone.utc))
    with args.output.open("a", encoding="utf-8") as stream:
        stream.write(f"dispatch={'true' if result['dispatch'] else 'false'}\n")
        stream.write(f"request_id={result['request_id']}\n")
    print("MOVIODDS_WEEKLY_CDB_SCHEDULER", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
