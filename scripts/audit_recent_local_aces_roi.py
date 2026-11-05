"""Read-only audit of recent frozen local Aces Results in the private release feed.

No paid API calls, ledger writes, CDB changes, or automatic result regrading.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from tbt.services.local_ace_results import local_ace_result_odds
from tbt.services.dashboard_kpis import published_results_metrics

_CUTOFF = "2026-11-01"
_ZONE = ZoneInfo("Europe/Bratislava")


def _day(value: object) -> str:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return ""
        return (stamp.astimezone(_ZONE) - timedelta(hours=6)).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return ""


def audit(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    days: dict[str, list[dict]] = defaultdict(list)
    source_rows = payload.get("results") or []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        day = _day(row.get("scheduled_at"))
        if not day or day < _CUTOFF:
            continue
        for publication in row.get("market_publications") or []:
            if not isinstance(publication, dict):
                continue
            result = publication.get("result") or {}
            if not isinstance(result, dict) or type(result.get("correct")) is not bool:
                continue
            local = local_ace_result_odds(row, publication)
            if local is None:
                continue
            # Do not mutate any source row or original publication.
            days[day].append({**row, "market_publications": [publication]})
    audited = {}
    for day in sorted(days):
        metrics = published_results_metrics({"results": days[day]}, "all")
        graded = metrics["wins"] + metrics["losses"]
        if metrics["stake_count"] != graded or abs(metrics["staked_units"] - graded) > 1e-6:
            raise AssertionError(f"Local Aces do not enter full ROI on {day}")
        audited[day] = {
            "wins": metrics["wins"], "losses": metrics["losses"], "stake_count": graded,
            "profit_units": round(metrics["profit_units"], 4),
            "roi_percent": round(metrics["roi"] * 100, 2) if metrics["roi"] is not None else None,
        }
    return {"source_results_rows": len(source_rows), "accepted_local_aces_by_day": audited,
            "total_local_aces": sum(item["stake_count"] for item in audited.values()),
            "audit_kind": "read_only_20261101_onward"}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: audit_recent_local_aces_roi.py PATH_TO_FEED_JSON")
    print(json.dumps(audit(Path(sys.argv[1])), ensure_ascii=False, sort_keys=True))
