"""Pre-settlement exact Aces repair from immutable private Telegram receipt.

This client never calls a tennis API and does not write CDB. The backend
performs native Results archive CAS append and independent read-back.
"""
from __future__ import annotations
import argparse, json, os, re, sys, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import telegram_daily_results as results
import telegram_offer_publisher as tg


def _post(base, day, receipt, mode, digest=""):
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", base):
        raise ValueError("Expected HTTPS BlinQ origin")
    token=os.getenv("BLINQ_LIVE_WORKER_TOKEN") or ""
    if not token:
        raise RuntimeError("Missing protected website worker token")
    data=json.dumps({"schema":1,"day":day,"receipt":receipt,
                     "expected_digest":digest},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(
        base+"/api/v1/internal/telegram/reconcile-daily-aces?mode="+mode,
        data=data, method="POST",
        headers={"Content-Type":"application/json","Accept":"application/json",
                 "X-Blinq-Worker-Token":token})
    try:
        with urllib.request.urlopen(req,timeout=55) as resp:
            if resp.status != 200:
                raise RuntimeError("Daily ACE reconciliation HTTP not OK")
            raw=resp.read(200001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Daily ACE reconciliation endpoint refused: HTTP "+
                           str(exc.code)) from None
    if len(raw)>200000:
        raise RuntimeError("Daily ACE reconciliation response too large")
    data=json.loads(raw)
    if (not isinstance(data,dict) or data.get("ok") is not True
            or data.get("day")!=day
            or data.get("provider_requests")!=0
            or data.get("cdb_writes")!=0
            or data.get("telegram_sends")!=0
            or data.get("status")!=("dry_run" if mode=="dry-run" else "verified")):
        raise RuntimeError("Invalid native archive result")
    return data


def _attempt_for_day(state,day):
    reposts=[batch for key,batch in (state.get("reposts") or {}).items()
             if key.startswith(day+":repost:") and isinstance(batch,dict)
             and batch.get("status")=="sent"
             and batch.get("supersedes_daily") is True]
    if len(reposts)>1:
        raise RuntimeError("Ambiguous superseding Telegram receipt")
    if reposts:
        return reposts[0]
    return (state.get("attempts") or {}).get(day+":daily:0620")


def reconcile(state, base, *, now=None, sender=_post):
    now=now or datetime.now(timezone.utc)
    day=results.unreported_day(state,now)
    if not day:
        return {"status":"skipped","reason":"no_unreported_issued_day"}
    receipt=_attempt_for_day(state,day)
    if not receipt:
        return {"status":"skipped","reason":"not_a_daily_telegram_issue"}
    prepared=sender(base,day,receipt,"dry-run")
    if prepared["net_new_aces"]<1:
        return {"status":"read_only","day":day,
                "already_verified":prepared["already_verified"],
                "pending_evidence":prepared["pending_evidence"],
                "net_new_aces":0}
    committed=sender(base,day,receipt,"commit",prepared["digest"])
    if (committed.get("digest")!=prepared["digest"]
            or committed.get("readback_new_aces")!=prepared["net_new_aces"]):
        raise RuntimeError("Daily ACE exact Results read-back mismatch")
    return {"status":"verified","day":day,
            "net_new_aces":committed["readback_new_aces"],
            "already_verified":committed["already_verified"],
            "pending_evidence":committed["pending_evidence"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url",required=True)
    parser.add_argument("--state",required=True)
    args=parser.parse_args()
    ledger=tg.load(Path(args.state))
    if not isinstance(ledger,dict) or not isinstance(ledger.get("attempts"),dict):
        raise RuntimeError("Invalid confirmed Telegram ledger")
    status=reconcile(ledger,args.api_url)
    # Never log names, event IDs, odds, source receipt rows or channel IDs.
    print("TELEGRAM_DAILY_ACES_RECONCILE "+json.dumps(status,sort_keys=True))


if __name__=="__main__":
    main()
