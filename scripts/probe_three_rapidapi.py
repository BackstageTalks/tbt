"""Bounded read-only test using the existing shared quota guard."""
import json, os, time
from pathlib import Path
from datetime import datetime, timezone
from _bootstrap import ROOT
from tbt.providers.guarded_rapidapi import GuardedRapidApiHttp

TARGETS = [("tennis-api4.p.rapidapi.com", [("/competitions/2", {})])]
report={"time":datetime.now(timezone.utc).isoformat(), "commit":os.getenv("GITHUB_SHA"), "run_id":os.getenv("GITHUB_RUN_ID"), "cdb_writes":0, "providers":[]}
key=os.environ["RAPIDAPI_KEY"]
def clean(s):
 return s.replace(key,"[REDACTED]")
for host, targets in TARGETS:
 item={"host":host,"responses":[],"attempts":0}
 report["providers"].append(item)
 try:
  with GuardedRapidApiHttp(key,host) as client:
   def capture(r):
    r.read()
    row={"path":r.request.url.path,"status":r.status_code,"bytes":len(r.content),"quota":{k:v for k,v in r.headers.items() if "ratelimit" in k.lower()}}
    try: row["payload"]=json.loads(clean(r.text))
    except Exception: row["body_prefix"]=clean(r.text[:500])
    item["responses"].append(row)
   client.client.event_hooks["response"]=[capture]
   try:
    for path,params in targets[:20]:
     r=client.get("https://"+host+path, params=params)
     if r.status_code>=400: break
     time.sleep(4)
   finally: item["attempts"]=client.attempts
 except Exception as exc:
  item["stopped"]=type(exc).__name__+": "+clean(str(exc))[:300]
Path(".cache/tbt/three-rapidapi").mkdir(parents=True,exist_ok=True)
Path(".cache/tbt/three-rapidapi/report.json").write_text(json.dumps(report,indent=2),encoding="utf8")
print(json.dumps({"run_id":report["run_id"],"providers":[{k:v for k,v in x.items() if k!="responses"}|{"statuses":[r["status"] for r in x["responses"]]} for x in report["providers"]]},indent=2))
