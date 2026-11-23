"""Read-only probe: does RapidAPI know historical ITF matches (no native ID in CDB)
and does it return statistics for them? Bounded requests, no CDB writes."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date, timedelta


def norm_last(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    parts = re.sub(r"[^a-z ]", " ", s).split()
    return parts[-1] if parts else ""


def event_names(raw: dict) -> tuple[str, str]:
    h = raw.get("homeTeam") or {}
    a = raw.get("awayTeam") or {}
    return norm_last(h.get("name") or h.get("shortName")), norm_last(a.get("name") or a.get("shortName"))


def has_stats(payload) -> bool:
    if isinstance(payload, dict):
        stats = payload.get("statistics") or payload.get("data") or []
        return bool(stats)
    return bool(payload)


def run(client, request: dict, max_stats_per_day: int = 5) -> dict:
    client.request_limit = int(request.get("max_requests", 400))
    report = {"schema": 1, "cdb_writes": 0, "samples": []}
    for sample in request["days"]:
        start = date.fromisoformat(sample["day"])
        wanted = {frozenset((norm_last(m["p1"]), norm_last(m["p2"]))) for m in sample["matches"]}
        found = {}
        itf_events = 0
        for k in range(7):
            day = start + timedelta(days=k)
            try:
                cats = client.calendar_categories(day)
            except Exception as exc:
                report["stopped"] = str(exc)[:160]
                break
            for cat in cats:
                name = json.dumps(cat).lower()
                if "itf" not in name:
                    continue
                cid = client._category_id(cat)
                if cid is None:
                    continue
                try:
                    events = client.category_events(cid, day)
                except Exception as exc:
                    report["stopped"] = str(exc)[:160]
                    break
                for raw in events or []:
                    itf_events += 1
                    key = frozenset(event_names(raw))
                    if key in wanted and raw.get("id"):
                        found[key] = raw["id"]
        stats_ok = 0
        tried = 0
        for eid in list(found.values())[:max_stats_per_day]:
            try:
                payload = client.event_statistics(eid)
                tried += 1
                stats_ok += int(has_stats(payload))
            except Exception:
                tried += 1
        report["samples"].append({"week": sample["day"], "cdb_matches": len(wanted),
                                  "rapidapi_itf_events": itf_events, "matched": len(found),
                                  "stats_tried": tried, "stats_available": stats_ok})
    report["requests"] = getattr(client, "request_count", None)
    return report


if __name__ == "__main__":
    from tbt.providers.rapidapi import RapidTennisClient
    req = json.load(open(".github/itf-stats-probe-request.json", encoding="utf-8"))
    rep = run(RapidTennisClient(), req)
    print("ITF_STATS_PROBE " + json.dumps(rep))
    sys.exit(0)
