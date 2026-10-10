"""Read-only, aggregate-only audit of private published Results; never prints identities."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CATEGORY_SET = {"top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}
MARKET_SET = {"aces", "double_faults"}
SELECTED = {"top_daily", "value", "ace", "double_faults", "sets", "games"}


def parse_datetime(value):
    if not value:
        return None
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    except (ValueError, TypeError):
        return None


def scan(payload: dict, day: str) -> dict:
    local = ZoneInfo("Europe/Bratislava")
    d = date.fromisoformat(day)
    first = datetime.combine(d, time(6), local)
    last = datetime.combine(d + timedelta(days=1), time(6), local)
    sources = payload.get("results") or []
    counted = Counter()
    unique = {}
    for row in sources:
        if not isinstance(row, dict):
            continue
        moment = parse_datetime(row.get("scheduled_at") or row.get("date"))
        if not moment or not (first <= moment.astimezone(local) < last):
            continue
        for publication in row.get("market_publications") or []:
            if not isinstance(publication, dict):
                continue
            section = str(publication.get("section") or "").lower()
            market = str(publication.get("market") or "").lower()
            if section not in CATEGORY_SET and market not in MARKET_SET:
                continue
            category = {"aces":"ace","double_faults":"double_faults"}.get(market, section)
            result = publication.get("result") or {}
            issued = bool(publication.get("issued_at")) or result.get("runtime_source") == "match_status_snapshot"
            if not issued or publication.get("excluded_reason"):
                continue
            status = str(result.get("status") or result.get("outcome") or "").lower()
            is_void = result.get("void") is True or status in {
                "void","push","retired","ret","cancelled","canceled","walkover","w/o"
            }
            settled = result.get("correct") in (True, False) or is_void
            counted[f"{category}_issued"] += 1
            counted[f"{category}_{'settled' if settled else 'pending'}"] += 1
            if not settled:
                continue
            identity = (
                str(row.get("event_id") or row.get("id") or row.get("match_id") or ""),
                market or "match_winner",
                str(publication.get("projection_scope") or ""),
                str(publication.get("projection_metric") or ""),
                str(publication.get("selection_id") or publication.get("selection") or "")
            )
            if not all((identity[0], identity[-1])):
                counted["unresolved_identity"] += 1
                continue
            unique.setdefault(identity, set()).add(category)
    grouped = Counter()
    for categories in unique.values():
        for category in categories:
            grouped[category] += 1
    by_selection = sum(bool(categories & SELECTED) for categories in unique.values())
    doubles_only = sum(bool(categories & {"doubles"}) for categories in unique.values())
    return {
        "date":day, "window":"06:00–06:00 Europe/Bratislava",
        "source":"private released feed.json RESULTS only, EXCLUDES Azure runtime archive",
        "source_results_rows":len(sources),
        "selected_categories":sorted(SELECTED),
        "settled_unique_selected":by_selection,
        "settled_unique_all":len(unique),
        "settled_unique_doubles":doubles_only,
        "settled_by_category":dict(sorted(grouped.items())),
        "issued_pending_by_category":dict(sorted(counted.items())),
    }


def _test():
    stamp = "2026-10-10T14:00:00+02:00"
    def pub(section, correct, market="match_winner"):
        return {"section":section,"market":market,"issued_at":stamp,
                "selection_id":"p1","result":{"correct":correct}}
    payload={"results":[
        {"event_id":"a","scheduled_at":stamp,"market_publications":[pub("top_daily",False),pub("value",False)]},
        {"event_id":"b","scheduled_at":stamp,"market_publications":[pub("doubles",True)]},
        {"event_id":"c","scheduled_at":stamp,"market_publications":[pub("ace",None,"aces")]},
    ]}
    report=scan(payload,"2026-10-10")
    assert report["settled_unique_selected"]==1, report
    assert report["settled_unique_all"]==2, report
    assert report["settled_unique_doubles"]==1, report
    assert report["issued_pending_by_category"]["ace_pending"]==1, report
    print("Results aggregate audit contract: PASS")


if __name__=="__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":
        _test()
    else:
        if len(sys.argv)!=2:
            raise SystemExit("Usage: python scripts/audit_results_filter_20261010.py <feed.json>")
        report=scan(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")),"2026-10-10")
        print(json.dumps(report,ensure_ascii=False,sort_keys=True))
