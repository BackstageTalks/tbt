"""Publish verified previous-day BlinQ results in the legacy Telegram format.

A read-only authenticated API supplies the official Results archive + exclusions.
This job does not call paid data providers, settle anything, or modify CDB.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

BRATISLAVA = ZoneInfo("Europe/Bratislava")
DAY_LABELS = (("top", "TOP"), ("value", "VALUE"), ("aces", "ESÁ"))
NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")
HEADER = "Data Betting by BackstageTalks"
FOOTER = "ℹ️ Analytical preview only\n🧠 by BackstageTalks Data Engine"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def instant(raw):
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Timezone required")
    return value.astimezone(timezone.utc)


def previous_day(now):
    local = now.astimezone(BRATISLAVA)
    if local.hour < 6:
        raise ValueError("Betting day has not closed yet")
    return (local.date() - timedelta(days=1)).isoformat()


def due(settings, now):
    if settings.get("enabled") is not True or settings.get("results_enabled") is not True:
        return None
    local = now.astimezone(BRATISLAVA)
    if local.hour < 6:
        return None
    clock = str(settings.get("results_time", "07:00"))
    if not re.fullmatch(r"(?:0[6-9]|1\d|2[0-3]):[0-5]\d", clock):
        raise ValueError("Results time must be 06:00 or later")
    hour, minute = map(int, clock.split(":"))
    target = datetime.combine(local.date(), time(hour, minute), tzinfo=BRATISLAVA)
    age = (now - target.astimezone(timezone.utc)).total_seconds()
    if 0 <= age <= 5400:
        return "results:" + previous_day(now)
    return None


def fetch(url, token, target):
    """TLS, secret worker header; no token, IDs or privileged data in logs."""
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+/api/v1/internal/telegram-results", url):
        raise ValueError("Invalid private results endpoint")
    if not token:
        raise RuntimeError("BLINQ_LIVE_WORKER_TOKEN is missing")
    request = urllib.request.Request(url + "?day=" + target,
                                     headers={"X-Blinq-Worker-Token": token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=25) as res:
            data = res.read(2_000_001)
    except Exception as exc:
        raise RuntimeError("Verified Results endpoint unavailable (" + type(exc).__name__ + ")") from None
    if len(data) > 2_000_000:
        raise RuntimeError("Results report exceeds safe limit")
    payload = json.loads(data)
    if payload.get("schema") != 1 or payload.get("betting_day") != target:
        raise RuntimeError("Results day/contract mismatch")
    if payload.get("source") != "blinq_issued_results_archive_read_only" or payload.get("coverage") != "recorded_results_only":
        raise RuntimeError("Results source lacks provenance")
    if not isinstance(payload.get("rows"), list):
        raise RuntimeError("Invalid results rows")
    return payload


def name_map(rows):
    names = list(dict.fromkeys(str(x.get("selection") or "").strip() for x in rows))
    mapping = {}
    colliding = {}
    for full in names:
        parts = full.split()
        surname = parts[-1] if parts else "—"
        colliding.setdefault(surname.casefold(), []).append(full)
    for full in names:
        parts = full.split()
        surname = parts[-1] if parts else "—"
        if len(colliding[surname.casefold()]) > 1 and len(parts) > 1:
            name = "".join(x[0].upper() + "." for x in parts[:-1]) + " " + surname
        else:
            name = surname
        mapping[full] = name
    return mapping


def render_section(rows, label, target, *, free=False):
    d = date.fromisoformat(target).strftime("%d.%m.%y")
    counts = {s: 0 for s in ("win", "loss", "void", "pending")}
    profit = stake = 0.0
    rendered = []
    names = name_map(rows)
    for idx, entry in enumerate(rows, 1):
        status = str(entry.get("status") or "pending")
        if status not in counts:
            raise ValueError("Invalid verified result outcome")
        counts[status] += 1
        marker = {"win": "✅", "loss": "❌", "void": "➖", "pending": "⏳"}[status]
        selection = str(entry.get("selection") or "—")
        try:
            clock = instant(entry["scheduled_at"]).astimezone(BRATISLAVA).strftime("%H:%M")
        except (ValueError, TypeError, KeyError):
            raise ValueError("Unverified scheduled result")
        try:
            odds = float(entry["odds"]) if entry.get("odds") is not None else None
            units = float(entry["profit"]) if entry.get("profit") is not None else None
            wager = float(entry["stake"]) if entry.get("stake") is not None else None
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid settled bet metrics") from exc
        import math
        if odds is not None and not math.isfinite(odds): raise ValueError("Nonfinite quote")
        if units is not None and not math.isfinite(units): raise ValueError("Nonfinite profit")
        if wager is not None and (not math.isfinite(wager) or wager <= 0): raise ValueError("Invalid stake")
        if status in ("win", "loss") and wager is not None and units is not None:
            stake += wager
            profit += units
        odds_text = f"{odds:.2f}" if odds is not None and odds > 1 else "—"
        units_text = f"{units:+.2f}u" if units is not None and wager is not None else ("Pending" if status == "pending" else "—")
        prefix = "🆓" if free else (NUMBERS[idx - 1] if idx <= len(NUMBERS) else str(idx) + ".")
        rendered.append(f"{prefix} {marker} {names.get(selection, selection)} | {clock} | {odds_text} | {units_text}")
    roi = f"ROI {profit / stake * 100:+.1f}%" if stake > 0 else "ROI —"
    aggregate = f"✅{counts['win']} ❌{counts['loss']} ➖{counts['void']} ⏳{counts['pending']} | {profit:+.2f}u | {roi}"
    # The settled archive is NOT a complete issued-pick inventory. Never imply
    # that unobserved historical picks are losses, wins, or 0 outstanding.
    return "\n".join([HEADER, "", f"📊 Results | {label}",
                      f"📅 {d}", "", *rendered, "",
                      aggregate, "📌 Potvrdené výsledky v archíve (nie úplný počet vydaných tipov).", "",
                      FOOTER])


def messages(payload, previous, free_event_id=None):
    if payload.get("betting_day") != previous or payload.get("source") != "blinq_issued_results_archive_read_only":
        raise ValueError("Previous day not verified")
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError("Invalid Results payload")
    messages = []
    for section, label in DAY_LABELS:
        selected = [x for x in rows if isinstance(x, dict) and x.get("section") == section]
        if not selected:
            continue
        selected.sort(key=lambda x: (str(x.get("scheduled_at") or ""), str(x.get("id") or "")))
        body = render_section(selected, label, previous)
        if len(body) > 4096:
            raise RuntimeError("Results message too long; fail rather than truncate official results")
        messages.append({"audience": "premium", "text": body, "section": section})
    # Only a previously reserved FREE publication can produce a FREE result.
    # Use the SAME archived TOP row; never infer a win from an absent result.
    if free_event_id:
        free_matches = [x for x in rows if isinstance(x, dict)
                        and x.get("section") == "top"
                        and str(x.get("event_id") or "") == str(free_event_id)]
        if len(free_matches) == 1:
            free_body = render_section(free_matches, "FREE", previous, free=True)
            if len(free_body) > 4096:
                raise RuntimeError("FREE Results message too long")
            messages.append({"audience": "free", "text": free_body, "section": "free"})
    return messages


def prepare(args):
    now = instant(args.now) if args.now else datetime.now(timezone.utc)
    from telegram_offer_publisher import config
    settings = config(args.config_url)
    key = due(settings, now)
    if key is None:
        print('{"status":"skipped","reason":"results_not_due"}')
        return
    state = read(args.state) if Path(args.state).is_file() else {"schema": 1, "attempts": {}}
    attempts = state.get("attempts")
    if not isinstance(attempts, dict):
        raise ValueError("Invalid reservations")
    target = previous_day(now)
    ident = target + ":" + key
    if ident in attempts:
        print('{"status":"skipped","reason":"results_already_reserved"}')
        return
    base = args.results_url
    payload = fetch(base, os.getenv("BLINQ_LIVE_WORKER_TOKEN", ""), target)
    free_event_id = (state.get("free_picks") or {}).get(target)
    outgoing = messages(payload, target, free_event_id=free_event_id)
    if not outgoing:
        print('{"status":"skipped","reason":"no_verified_results"}')
        return
    directory = Path(args.output)
    write(directory / "messages.json", outgoing)
    attempts[ident] = {"reserved_at": now.isoformat(), "category": "results",
                       "sha256": hashlib.sha256(json.dumps(outgoing, ensure_ascii=False).encode()).hexdigest()}
    write(directory / "state.json", {**state, "schema": 1,
          "attempts": dict(list(attempts.items())[-200:])})
    (directory / "ready").write_text(ident, encoding="utf-8")
    print(json.dumps({"status": "reserved", "day": target, "messages": len(outgoing)}))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config-url", default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/ui-config")
    p.add_argument("--results-url", default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/internal/telegram-results")
    p.add_argument("--state", default="/tmp/blinq-tg-ledger/ops/telegram-bot-state.json")
    p.add_argument("--output", default="/tmp/blinq-telegram-results")
    p.add_argument("--now", default="")
    prepare(p.parse_args())


if __name__ == "__main__":
    main()
