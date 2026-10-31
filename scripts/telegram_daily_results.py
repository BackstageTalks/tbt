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


def daily_report(sent, archive_rows, day_text, footer):
    """One premium report for the entire exact sent TOP/Value/Aces cohort.

    The current day is never read as settlement; only official previous-day
    archive matches are accepted. FREE is a separate destination/report.
    Telegram messages are split losslessly on UTF-16 boundaries when necessary.
    """
    categories=("top","value","aces")
    premium=[row for category in categories for row in sent if row.get("channel")==category]
    if not premium:
        return []
    icons={"won":"✅","lost":"❌","void":"➖","pending":"⏳"}
    counts={key:0 for key in icons}
    units=0.0;priced=0
    lines=[]
    for index,row in enumerate(premium,1):
        item=evaluate(row,archive_rows)
        status=item["status"]
        counts[status]+=1
        if item["units"] is not None:
            units+=item["units"]
            priced+=item["stake"]
        odds=tg.num(row.get("odds"))
        price_text=f"{odds:.2f}" if odds is not None and odds>1 else "—"
        unit_text=(f"{item['units']:+.2f}u" if item["units"] is not None else
                   "Pending" if status=="pending" else
                   "+0.00u" if status=="void" else "—")
        index_text=tg.NUMBER_EMOJIS[index-1] if index<=10 else f"{index}."
        selected=str(row.get("name") or "—").split()
        short=selected[-1] if selected else "—"
        time=tg.stamp(row["scheduled_at"]).astimezone(tg.TZ).strftime("%H:%M")
        lines.append(f"{index_text} {icons[status]} {short} | {time} | {price_text} | {unit_text}")

    settled=counts["won"]+counts["lost"]+counts["void"]
    decided=counts["won"]+counts["lost"]
    def pct(n):
        return f"{n/settled*100:.1f}%" if settled else "—"
    hit=f"{counts['won']/decided*100:.1f}%" if decided else "—"
    roi=f"{units/priced*100:+.1f}%" if priced else "—"
    cash=f"{units:+.2f}u" if priced else "—"
    summary=[
      f"✅ WIN {counts['won']} ({pct(counts['won'])}) | ❌ LOSS {counts['lost']} ({pct(counts['lost'])})",
      f"➖ VOID {counts['void']} ({pct(counts['void'])}) | ⏳ PENDING {counts['pending']}",
      f"🎯 Úspešnosť {hit} ({counts['won']}/{decided})",
      f"💰 Zisk {cash} | 📈 ROI {roi}" + (f" ({priced}u)" if priced else ""),
    ]
    if counts["pending"]:
        summary.append("⏳ Priebežné: zostávajú nevyhodnotené tipy z odoslanej ponuky.")
    if decided>priced:
        summary.append("ℹ️ Bezkurzové projekcie sú mimo výpočtu units/ROI.")
    if not settled:
        summary.append("ℹ️ Zatiaľ nie je potvrdený výsledok; percentá nie sú dostupné.")
    prefix="\n".join([tg.HEADER,"","📊 Results | BlinQ",f"📅 {datetime.fromisoformat(day_text):%d.%m.%y}",""])
    final="\n"+"\n".join(summary)+"\n\n"+footer
    normal_footer="\n\n"+footer
    result=[];current=[]
    def units_len(value):
        return len(value.encode("utf-16-le"))//2
    for line in lines:
        candidate="\n".join([*current,line])
        if units_len(prefix+candidate+final)>4096:
            if not current:
                # If final summary is unusually large, let the row stay on a
                # page without the summary and validate it independently.
                if units_len(prefix+line+normal_footer)>4096:
                    raise RuntimeError("One settled pick cannot fit in Telegram")
                current=[line]
            else:
                text=prefix+"\n".join(current)+normal_footer
                if units_len(text)>4096:
                    raise RuntimeError("Telegram Results page overflow")
                result.append({"audience":"premium","text":text,
                               "counts":{key:0 for key in icons},"priced_decisions":0})
                current=[line]
    # The full, single-day summary always appears on the final page.
    ending=prefix+"\n".join(current)+final
    if units_len(ending)>4096:
        if not current or units_len(prefix+"\n".join(current)+normal_footer)>4096:
            raise RuntimeError("Telegram results summary does not fit")
        result.append({"audience":"premium","text":prefix+"\n".join(current)+normal_footer,
                       "counts":{key:0 for key in icons},"priced_decisions":0})
        ending=prefix+"\n".join(summary)+"\n\n"+footer
    if units_len(ending)>4096:
        raise RuntimeError("Telegram results summary exceeds character limit")
    result.append({"audience":"premium","text":ending,
                   "counts":counts,"priced_decisions":priced})
    return result


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
    posts=daily_report(sent,verified,target_day,footer)
    free=report_rows(sent,verified,"free",target_day,footer)
    if free: posts.append(free)
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
