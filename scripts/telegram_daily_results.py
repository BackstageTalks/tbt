"""Read-only previous betting-day Telegram results from verified BlinQ archive.

Never grade from prediction confidence or model output. Only persisted
match-status-snapshot settlements are trusted. Pending rows remain pending.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import telegram_offer_publisher as tg


def previous_day(now):
    local = now.astimezone(tg.TZ)
    if local.hour < 6:
        raise RuntimeError("The previous BlinQ betting day is not closed yet")
    return (local.date() - timedelta(days=1)).isoformat()


def archive(url, day):
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", url):
        raise ValueError("Only HTTPS results API is allowed")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Invalid betting day")
    key = os.getenv("BLINQ_LIVE_WORKER_TOKEN") or ""
    if not key:
        raise RuntimeError("Missing existing BLINQ_LIVE_WORKER_TOKEN")
    request = urllib.request.Request(
        url + "/api/v1/internal/telegram/settled-results?day=" + day,
        headers={"Accept": "application/json", "X-Blinq-Worker-Token": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError("Verified settlements unavailable")
            body = response.read(5_000_001)
    except Exception as exc:
        raise RuntimeError("Verified settlement endpoint is unavailable: " + exc.__class__.__name__) from None
    if len(body) > 5_000_000:
        raise RuntimeError("Results API response exceeds limit")
    payload = json.loads(body)
    if (not isinstance(payload, dict) or payload.get("schema") != 1
            or payload.get("betting_day") != day
            or payload.get("source") != "verified_match_status_snapshot"
            or not isinstance(payload.get("rows"), list)):
        raise RuntimeError("Invalid verified settlement response")
    return payload["rows"]


def extract_sent(state, target_day):
    attempts = state.get("attempts") or {}
    if not isinstance(attempts, dict):
        raise ValueError("Corrupted Telegram delivery ledger")
    picked = {}
    for key, attempt in sorted(attempts.items()):
        if not key.startswith(target_day + ":") or not isinstance(attempt, dict):
            continue
        if attempt.get("status") != "sent":
            continue
        records = attempt.get("rows") or []
        if not isinstance(records, list) or not records:
            raise RuntimeError("Missing exact sent-pick references")
        if not attempt.get("message_ids"):
            raise RuntimeError("Sent attempt without Telegram receipt")
        for row in records:
            if not isinstance(row, dict):
                raise RuntimeError("Invalid sent-pick reference")
            if row.get("channel") not in ("top", "value", "aces", "free"):
                raise RuntimeError("Unexpected Telegram category")
            if not (row.get("event_id") and row.get("selection_id") and row.get("scheduled_at")):
                raise RuntimeError("Incomplete sent-pick reference")
            if tg.day(tg.stamp(row["scheduled_at"])) != target_day:
                raise RuntimeError("Sent reference belongs to another betting day")
            identity=(row["channel"], str(row["event_id"]), str(row["selection_id"]),
                      str(row.get("publication_key") or ""), str(row.get("market_line") or ""),
                      str(row.get("projection_direction") or ""))
            existing=picked.get(identity)
            if existing is not None and existing != row:
                raise RuntimeError("Conflicting sent Telegram pick identity")
            picked[identity] = row
    return list(picked.values())


def match_result(sent, settled):
    """Match exactly one authoritative settlement (no fuzzy name matches)."""
    found=[]
    for row in settled:
        if not isinstance(row, dict):
            continue
        if any(str(row.get(key) or "") != str(sent.get(key) or "")
               for key in ("event_id", "selection_id", "section", "market")):
            continue
        frozen_pub=str(sent.get("publication_key") or "")
        archived_pub=str(row.get("publication_key") or "")
        if frozen_pub and frozen_pub != archived_pub:
            continue
        if sent.get("market")=="aces":
            if str(sent.get("market_line") or "") != str(row.get("market_line") or ""):
                continue
            if str(sent.get("projection_direction") or "") != str(row.get("projection_direction") or ""):
                continue
        result=row.get("result")
        if not isinstance(result,dict) or result.get("runtime_source")!="match_status_snapshot":
            continue
        if type(result.get("correct")) is not bool and result.get("void") is not True:
            continue
        found.append(row)
    if len(found)>1:
        raise RuntimeError("Ambiguous archive settlements for an exact published pick")
    return found[0] if found else None


def evaluate(sent, archive_rows):
    record=match_result(sent,archive_rows)
    result=(record or {}).get("result") or {}
    if record is None:
        return {"status":"pending","units":None,"stake":0,"odds":sent.get("odds")}
    if result.get("void") is True:
        return {"status":"void","units":0.0,"stake":0,"odds":sent.get("odds")}
    good=result.get("correct")
    if type(good) is not bool:
        return {"status":"pending","units":None,"stake":0,"odds":sent.get("odds")}
    odds=tg.num(sent.get("odds"))
    archived_odds=tg.num(record.get("odds"))
    priced=(odds is not None and odds>1 and archived_odds is not None
            and abs(odds-archived_odds)<0.000001)
    if sent["market"]=="aces" and record.get("price_status")!="priced_projection":
        priced=False
    units=(odds-1 if good else -1.0) if priced else None
    return {"status":"won" if good else "lost",
            "units":units,"stake":1 if priced else 0,"odds":odds}


def report_rows(rows, archive_rows, category, day_text, footer):
    icons={"won":"✅","lost":"❌","void":"➖","pending":"⏳"}
    counts={name:0 for name in icons}
    units=0.0; priced=0
    labels={"top":"TOP","value":"VALUE","aces":"ACES","free":"FREE"}
    ordered=[r for r in rows if r.get("channel")==category]
    if not ordered:
        return None
    if len(ordered)>40:
        raise RuntimeError("Too many Telegram report entries")
    date_text=datetime.fromisoformat(day_text).strftime("%d.%m.%y")
    lines=[tg.HEADER,"",f"📊 Results | BlinQ {labels[category]}",f"📅 {date_text}",""]
    for i,row in enumerate(ordered,1):
        item=evaluate(row,archive_rows)
        status=item["status"];counts[status]+=1
        if item["units"] is not None:units+=item["units"];priced+=item["stake"]
        price=tg.num(row.get("odds"));price_text=f"{price:.2f}" if price and price>1 else "—"
        unit_text=f"{item['units']:+.2f}u" if item["units"] is not None else (
            "Pending" if status=="pending" else "—" if status!="void" else "+0.00u")
        symbol="🆓" if category=="free" else tg.NUMBER_EMOJIS[i-1] if i<=10 else f"{i}."
        selected=str(row.get("name") or "—").strip().split()
        name=selected[-1] if selected else "—"
        start=tg.stamp(row["scheduled_at"]).astimezone(tg.TZ).strftime("%H:%M")
        lines.append(f"{symbol} {icons[status]} {name} | {start} | {price_text} | {unit_text}")
    roi=f"ROI {units/priced*100:+.1f}%" if priced else "ROI —"
    lines.extend(["",f"✅{counts['won']} ❌{counts['lost']} ➖{counts['void']} ⏳{counts['pending']} | {units:+.2f}u | {roi}"])
    if counts["pending"]:
        lines.append("⏳ Priebežné vyhodnotenie – neuzavreté zápasy bez výsledku.")
    if (counts["won"]+counts["lost"])>priced:
        lines.append("ℹ️ Neocenené projekcie sú mimo výpočtu jednotiek a ROI.")
    lines.extend(["",footer])
    message="\n".join(lines)
    if len(message)>4096:
        raise RuntimeError("Telegram results message too large")
    return {"audience":"free" if category=="free" else "premium",
            "text":message,
            "counts":counts,
            "priced_decisions":priced}



def _pct(numerator, denominator):
    return f"{numerator / denominator * 100:.1f}%" if denominator else "—"


def combined_daily_report(rows, archive_rows, day_text, footer):
    """One premium daily results scorecard for the entire confirmed sent offer.

    Free picks are a separate audience and must never inflate premium totals.
    The only monetary denominator is the number of genuinely priced 1u
    decisions. VOID/PENDING and projection-only picks don't create ROI stakes.
    """
    categories=("top", "value", "aces")
    ordered=[(category,row) for category in categories
             for row in rows if row.get("channel")==category]
    if not ordered:
        return []
    stats={section:{"won":0,"lost":0,"void":0,"pending":0,"units":0.0,"priced":0}
           for section in categories}
    names={}
    for _,row in ordered:
        full=str(row.get("name") or "—").strip()
        short=full.split()[-1] if full.split() else "—"
        names.setdefault(short.casefold(),set()).add(full)
    lines=[]
    for index,(section,row) in enumerate(ordered,1):
        outcome=evaluate(row,archive_rows)
        status=outcome["status"]
        if status not in stats[section]:
            raise RuntimeError("Unexpected settlement status in verified report")
        bucket=stats[section]
        bucket[status]+=1
        if outcome["units"] is not None:
            bucket["units"]+=outcome["units"]
            bucket["priced"]+=outcome["stake"]
        full=str(row.get("name") or "—").strip()
        short=full.split()[-1] if full.split() else "—"
        name=full if len(names[short.casefold()])>1 else short
        time=tg.stamp(row["scheduled_at"]).astimezone(tg.TZ).strftime("%H:%M")
        odds=tg.num(row.get("odds"))
        odds_text=f"{odds:.2f}" if odds is not None and odds>1 else "—"
        result_text=(f"{outcome['units']:+.2f}u" if outcome["units"] is not None else
                     "+0.00u" if status=="void" else
                     "Pending" if status=="pending" else "—")
        index_text=tg.NUMBER_EMOJIS[index-1] if index<=len(tg.NUMBER_EMOJIS) else f"{index}."
        icon={"won":"✅","lost":"❌","void":"➖","pending":"⏳"}[status]
        lines.append(f"{index_text} {icon} {name} | {time} | {odds_text} | {result_text}")

    total={status:sum(stats[s][status] for s in categories) for status in ("won","lost","void","pending")}
    total_profit=sum(stats[s]["units"] for s in categories)
    total_staked=sum(stats[s]["priced"] for s in categories)
    def summary(section):
        s=stats[section]
        decided=s["won"]+s["lost"]
        label={"top":"TOP","value":"VALUE","aces":"ACES"}[section]
        rate=_pct(s["won"],decided)
        roi=(_pct(s["units"],s["priced"]) if s["priced"] else "—")
        return (f"{label} · WIN {s['won']} | LOSS {s['lost']} | VOID {s['void']} | "
                f"PENDING {s['pending']} | Win {rate} | {s['units']:+.2f}u | ROI {roi}")
    summaries=[summary(s) for s in categories if sum(stats[s][k] for k in ("won","lost","void","pending"))]
    decisions=total["won"]+total["lost"]
    win=_pct(total["won"],decisions)
    roi=_pct(total_profit,total_staked) if total_staked else "—"
    summary_tail=[
        "📊 Denný súhrn",
        *summaries,
        (f"✅ WIN {total['won']} | ❌ LOSS {total['lost']} | "
         f"➖ VOID {total['void']} | ⏳ PENDING {total['pending']}"),
        f"🎯 Úspešnosť {win} | 💰 Zisk {total_profit:+.2f}u | 📈 ROI {roi}",
    ]
    if total["pending"]:
        summary_tail.append("⏳ Priebežné vyhodnotenie: neuzavreté zápasy sa počítajú ako Pending.")
    if decisions > total_staked:
        summary_tail.append("ℹ️ Projekcie bez potvrdeného kurzu sú mimo zisku a ROI.")
    day_label=datetime.fromisoformat(day_text).strftime("%d.%m.%Y")
    header=[tg.HEADER, f"📊 Results | {day_label}"]
    closing="\n".join([*summary_tail,"",footer])
    def size(text):
        return len(text.encode("utf-16-le"))//2
    def compose(rows_text, include_closing=False):
        parts=[*header]
        if rows_text:
            parts.append("\n".join(rows_text))
        if include_closing:
            parts.append(closing)
        else:
            parts.append(footer)
        return "\n\n".join(parts)
    # Prefer one complete daily report when it fits. For longer days,
    # all rows are preserved, and the financial/quality summary is posted last.
    if size(compose(lines,True))<=4096:
        pages=[compose(lines,True)]
    else:
        pages=[]
        current=[]
        for line in lines:
            if size(compose(current+[line]))>4096:
                if not current:
                    raise RuntimeError("A settlement line is too long for Telegram")
                pages.append(compose(current))
                current=[]
            current.append(line)
        if size(compose(current,True))<=4096:
            pages.append(compose(current,True))
        else:
            if current:
                pages.append(compose(current))
            if size(compose([],True))>4096:
                raise RuntimeError("Telegram settlement summary exceeds 4096 units")
            pages.append(compose([],True))
    if any(size(message)>4096 for message in pages):
        raise RuntimeError("Telegram result pagination exceeds message limit")
    return [
        {"audience":"premium","text":page,
         "counts":total if i==len(pages)-1 else {k:0 for k in total},
         "priced_decisions":total_staked if i==len(pages)-1 else 0,
         "profit_units":total_profit if i==len(pages)-1 else 0.0}
        for i,page in enumerate(pages)
    ]


def prepare(args):
    now=tg.stamp(args.now) if args.now else datetime.now(timezone.utc)
    target_day=previous_day(now)
    local=now.astimezone(tg.TZ)
    if args.external_tick and not (local.hour==7 or (local.hour==8 and local.minute<30)):
        print(json.dumps({"status":"skipped","reason":"outside_07_local_window"}))
        return
    cfg=tg.config(args.config_url)
    if cfg.get("enabled") is not True or cfg.get("results_enabled") is not True:
        print(json.dumps({"status":"skipped","reason":"results_disabled"}))
        return
    state=tg.load(args.state)
    if not isinstance(state,dict) or not isinstance(state.get("attempts"),dict):
        raise RuntimeError("Invalid durable Telegram state")
    key="results:"+target_day
    if key in state["attempts"]:
        print(json.dumps({"status":"skipped","reason":"result_already_reserved"}))
        return
    sent=extract_sent(state,target_day)
    if not sent:
        print(json.dumps({"status":"skipped","reason":"no_confirmed_sent_offers"}))
        return
    verified=archive(args.api_url,target_day)
    footer=tg.branded_footer(cfg.get("footer"))
    # Premium: one chronological-by-section scorecard, preserving every
    # actually sent TOP -> Value -> Aces pick and a total daily summary.
    # FREE is separately graded but excluded from the premium denominator.
    posts=combined_daily_report(sent,verified,target_day,footer)
    free=report_rows(sent,verified,"free",target_day,footer)
    if free:
        posts.append(free)
    if not posts:
        print(json.dumps({"status":"skipped","reason":"no_results_to_report"}))
        return
    state["attempts"][key]={
        "status":"reserved","reserved_at":now.isoformat(),
        "betting_day":target_day,
        "counts":{k:sum(p["counts"][k] for p in posts) for k in ("won","lost","void","pending")},
    }
    out=Path(args.output)
    tg.save(out/"messages.json",[{"audience":p["audience"],"text":p["text"]} for p in posts])
    tg.save(out/"state.json",state)
    out.mkdir(parents=True,exist_ok=True)
    (out/"ready").write_text(key,encoding="utf-8")
    print(json.dumps({"status":"reserved","day":target_day,"messages":len(posts),
                      "counts":state["attempts"][key]["counts"]}))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["prepare"])
    parser.add_argument("--config-url",default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/ui-config")
    parser.add_argument("--api-url",default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net")
    parser.add_argument("--state",default="ops/telegram-bot-state.json")
    parser.add_argument("--output",default="/tmp/blinq-telegram")
    parser.add_argument("--now",default="")
    parser.add_argument("--external-tick",action="store_true")
    args=parser.parse_args()
    prepare(args)
