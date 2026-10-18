"""Probe the already-used secondary Tennis API host for historical rankings."""
from __future__ import annotations

import json
import os
from pathlib import Path


from _bootstrap import ROOT  # noqa: F401
from tbt.providers.guarded_rapidapi import GuardedRapidApiHttp

HOST="tennis-api-atp-wta-itf.p.rapidapi.com"
BASE=f"https://{HOST}"


def shape(value):
    if isinstance(value, dict):
        return {"type":"dict","keys":sorted(value.keys())[:30],
                "sample":{str(k):shape(v) for k,v in list(value.items())[:6]}}
    if isinstance(value, list):
        return {"type":"list","len":len(value),"first":shape(value[0]) if value else None}
    return {"type":type(value).__name__}


def main():
    key=os.getenv("RAPIDAPI_KEY","").strip()
    if not key:
        raise SystemExit("RAPIDAPI_KEY missing")
    # Mandatory shared-quota + provider-header verification on every probe.
    targets=[
        ("/tennis/v2/ranking/atp/player/68074/history",{"months":"24"}),
        ("/tennis/v2/ranking/atp",{"date":"14.09.2026","group":"singles","page":"1","limit":"10"}),
    ]
    results=[]
    remaining=None
    with GuardedRapidApiHttp(key, HOST) as client:
        for path,params in targets:
            response=client.get(BASE+path,params=params)
            remaining=response.headers.get("x-ratelimit-requests-remaining")
            row={"path":path,"params":params,"status":response.status_code}
            try:
                payload=response.json()
                row["shape"]=shape(payload)
            except Exception:
                row["body_prefix"]=response.text[:300]
            results.append(row)
    report={
        "schema":1,
        "host":HOST,
        "request_count":len(results),
        "provider_remaining_header":remaining,
        "production_mutated":False,
        "results":results,
    }
    out=Path(".cache/tbt/ranking-history/secondary-probe.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
