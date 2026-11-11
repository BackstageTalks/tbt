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


def _aces_key(row):
    """Match exact issued O/U contracts, not only their event or player."""
    return tuple(str(row.get(key) or "") for key in (
        "channel", "section", "market", "event_id", "selection_id",
        "publication_key", "market_line", "projection_direction",
    ))


def _receipts_for_day(state, day):
    """Original daily receipt plus genuinely new ACES in sent daily refreshes.

    Never resubmit a refreshed copy of an original contract: the native CAS
    writer correctly rejects its later `sent_at` as an issuance-time conflict.
    Keep all private ledger objects unchanged and use the existing native writer.
    """
    reposts = [batch for key, batch in (state.get("reposts") or {}).items()
               if key.startswith(day + ":repost:") and isinstance(batch, dict)
               and batch.get("status") == "sent"
               and batch.get("supersedes_daily") is True]
    if len(reposts) > 1:
        raise RuntimeError("Ambiguous superseding Telegram receipt")
    if reposts:
        return reposts

    attempts = state.get("attempts") or {}
    original_key = day + ":daily:0620"
    original = attempts.get(original_key)
    if not isinstance(original, dict) or original.get("status") != "sent":
        return []

    seen = {}
    for row in original.get("rows") or []:
        if isinstance(row, dict) and row.get("channel") == "aces":
            key = _aces_key(row)
            if key in seen:
                raise RuntimeError("Duplicated original Telegram ACES contract")
            seen[key] = row

    receipts = [original]
    for key, batch in sorted(attempts.items()):
        if (not key.startswith(day + ":daily:refresh-")
                or not isinstance(batch, dict) or batch.get("status") != "sent"):
            continue
        added = []
        for row in batch.get("rows") or []:
            if not isinstance(row, dict) or row.get("channel") != "aces":
                continue
            identity = _aces_key(row)
            previous = seen.get(identity)
            if previous is not None:
                if previous != row:
                    raise RuntimeError("Conflicting duplicate refreshed ACES contract")
                continue
            seen[identity] = row
            added.append(row)
        if added:
            # Exact subset of a confirmed issuance, with original message IDs,
            # send timestamp and contract fields. Do not mutate the ledger.
            isolated = dict(batch)
            isolated["rows"] = added
            receipts.append(isolated)
    return receipts


def reconcile(state, base, *, now=None, sender=_post):
    now = now or datetime.now(timezone.utc)
    day = results.unreported_day(state, now)
    if not day:
        return {"status": "skipped", "reason": "no_unreported_issued_day"}
    receipts = _receipts_for_day(state, day)
    if not receipts:
        return {"status": "skipped", "reason": "not_a_daily_telegram_issue"}

    totals = {"already_verified": 0, "pending_evidence": 0, "net_new_aces": 0}
    for receipt in receipts:
        prepared = sender(base, day, receipt, "dry-run")
        if any(type(prepared.get(key)) is not int or prepared[key] < 0
               for key in totals):
            raise RuntimeError("Invalid daily ACES dry-run counts")
        totals["already_verified"] += prepared["already_verified"]
        totals["pending_evidence"] += prepared["pending_evidence"]
        if prepared["net_new_aces"] < 1:
            continue

        committed = sender(base, day, receipt, "commit", prepared["digest"])
        if (committed.get("digest") != prepared["digest"]
                or committed.get("readback_new_aces") != prepared["net_new_aces"]):
            raise RuntimeError("Daily ACE exact Results read-back mismatch")
        totals["net_new_aces"] += committed["readback_new_aces"]

    return {"status": "verified" if totals["net_new_aces"] else "read_only",
            "day": day, **totals}


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
