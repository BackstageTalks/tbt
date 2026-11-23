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
        st, ev = get(c, f"/api/tennis/events/{d.day}/{d.month}/{d.year}")
        events = (ev or {}).get("events", []) if isinstance(ev, dict) else []
        itf = next((e for e in events if "itf" in json.dumps(e.get("tournament", {})).lower()), None)
        chall = next((e for e in events if "challenger" in json.dumps(e.get("tournament", {})).lower()), None)
        for label, e in (("ITF", itf), ("CHALLENGER", chall)):
            if not e:
                print("no", label, "event"); continue
            eid = e["id"]; season = (e.get("season") or {}).get("id")
            home = (e.get("homeTeam") or {}).get("id")
            print(f"\n=== {label} event {eid} season {season} home {home} {e.get('tournament',{}).get('name')}")
            for pid in (sk[:2] or ["1"]):
                st, b = get(c, f"/api/tennis/event/{eid}/odds/{pid}/all"); show(b, 500)
            st, b = get(c, f"/api/odds/season/{season}/provider/{sk[0] if sk else 1}/all"); show(b, 600)
            if isinstance(b, dict):
                print("SEASON_ODDS_EVENTS", len(json.dumps(b)), "bytes")
            st, b = get(c, f"/api/tennis/team/{home}/rankings"); show(b, 600)
            st, b = get(c, f"/api/tennis/team/{home}/year-statistics/{d.year}"); show(b, 700)
        if sk:
            st, b = get(c, f"/api/tennis/events/odds/{d.day}/{d.month}/{d.year}/{sk[0]}"); show(b, 400)
    print(f"\nPROBE_DONE calls={calls}")


if __name__ == "__main__":
    main()
