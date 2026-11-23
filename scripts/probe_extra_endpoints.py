#!/usr/bin/env python3
"""Read-only probe (<=25 paid calls) of unused tennisapi1 endpoints:
SK bookmaker providers, per-provider odds, season odds, player rankings,
player year statistics. Prints compact summaries only; writes nothing."""
from __future__ import annotations
import json, os
from datetime import date, timedelta
from _bootstrap import ROOT  # noqa: F401
from tbt.providers.guarded_rapidapi import GuardedRapidApiHttp

H = "tennisapi1.p.rapidapi.com"
MAX = 25
calls = 0


def get(c, path):
    global calls
    if calls >= MAX:
        raise SystemExit("probe cap reached")
    calls += 1
    r = c.get(f"https://{H}{path}")
    try:
        body = r.json()
    except Exception:
        body = None
    print(f"\n### {path} -> HTTP {r.status_code} remaining={c.remaining}")
    return r.status_code, body


def show(body, n=700):
    print(json.dumps(body, ensure_ascii=False)[:n] if body is not None else "<no json>")


def main():
    with GuardedRapidApiHttp(os.environ["RAPIDAPI_KEY"], H) as c:
        prov = {}
        for typ in ("web", "mobile"):
            st, b = get(c, f"/api/odds/providers/SK/{typ}")
            show(b, 400)
            for p in (b or {}).get("providers", []) if isinstance(b, dict) else []:
                q = p.get("provider", p)
                prov[str(q.get("id"))] = q.get("name") or q.get("slug")
            if prov:
                break
        print("\nSK_PROVIDERS", json.dumps(prov, ensure_ascii=False))
        sk = [i for i, n in prov.items() if any(k in str(n).lower() for k in ("fortuna", "tipsport", "nike", "doxx"))]
        print("SK_BOOKS", sk)
        d = date.today() - timedelta(days=1)
        tok = f"{d.day}/{d.month}/{d.year}"
        st, cats = get(c, f"/api/tennis/calendar/{tok}/categories")
        rows = (cats or {}).get("categories", []) if isinstance(cats, dict) else []
        picks = {}
        for row in rows:
            cat = row.get("category", row)
            name = json.dumps(cat).lower()
            for label in ("itf", "challenger"):
                if label in name and label not in picks:
                    picks[label] = cat.get("id")
        print("CATEGORIES", picks)
        for label, cid in picks.items():
            st, ev = get(c, f"/api/tennis/category/{cid}/events/{tok}")
            events = [e for e in ((ev or {}).get("events", []) if isinstance(ev, dict) else [])
                      if (e.get("status") or {}).get("type") == "finished"]
            if not events:
                print("no finished", label); continue
            e = events[0]
            eid = e["id"]; season = (e.get("season") or {}).get("id")
            home = (e.get("homeTeam") or {}).get("id")
            print(f"\n=== {label} event {eid} season {season} home {home} {e.get('tournament',{}).get('name')} events_in_cat={len(events)}")
            st, b = get(c, f"/api/tennis/event/{eid}/odds/1/all"); show(b, 500)
            st, b = get(c, f"/api/odds/season/{season}/provider/1/all"); show(b, 500)
            if isinstance(b, dict):
                print("SEASON_ODDS_KEYS", list(b)[:10], "bytes", len(json.dumps(b)))
                for k, v in b.items():
                    if isinstance(v, (list, dict)):
                        print("SEASON_ODDS_COUNT", k, len(v))
            st, b = get(c, f"/api/tennis/player/{home}/rankings"); show(b, 500)
            st, b = get(c, f"/api/tennis/team/{home}/year-statistics/{d.year}"); show(b, 500)
    print(f"\nPROBE_DONE calls={calls}")


if __name__ == "__main__":
    main()
