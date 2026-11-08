"""Telegram-only 'VIAC ES' feed from the exact tennis-ball marker on BlinQ.

This is an independent *most Aces player* signal, NOT player-total O/U.
Read-only verified current offer + public serving canary. Original daily
Telegram ledger / CDB / model results remain unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import unicodedata
import urllib.request

import telegram_offer_publisher as tg


def _normal(value):
    plain = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", plain).lower().split())


def ball_player(row):
    """Match the website's aceLeaderHintHtml marker, not its O/U selection."""
    if not isinstance(row, dict) or str(row.get("market") or row.get("projection_metric") or "").lower() != "aces":
        return None
    players = [row.get("player1"), row.get("player2")]
    if not all(isinstance(p, dict) and p.get("id") and p.get("name") for p in players):
        return None
    if str(players[0]["id"]) == str(players[1]["id"]):
        return None
    hint = _normal(row.get("aces_superiority_hint") or row.get("projection_subject"))
    hint_id = str(row.get("aces_superiority_player_id") or row.get("projection_subject_id") or "").strip()
    if not hint and not hint_id:
        return None
    matches = []
    for player in players:
        pid = str(player["id"]).strip()
        by_name = bool(hint and (hint == _normal(player["name"]) or hint == _normal(pid)))
        by_id = bool(hint_id and hint_id == pid)
        if by_name or by_id:
            matches.append(player)
    if len(matches) != 1:
        return None  # zero/ambiguous website balls are not guesses
    if hint_id and str(matches[0]["id"]) != hint_id:
        return None  # contradictory ID and name evidence
    if hint and hint != _normal(matches[0]["name"]) and hint != _normal(matches[0]["id"]):
        return None
    return matches[0]


def offered_rows(snapshot, now):
    """Only current, unstarted, confirmed source rows carrying ONE exact ball."""
    day = tg.day(now)
    generation = tg.stamp(snapshot["generated_at"])
    if (snapshot.get("confirmed_only") is not True
            or snapshot.get("betting_day") != day
            or tg.day(generation) != day
            or generation > now + timedelta(minutes=5)):
        raise ValueError("Unconfirmed/stale/wrong-day website offer")
    rows = snapshot.get("ace_picks")
    if not isinstance(rows, list):
        raise ValueError("Missing ACES website offer")
    selected = []
    identities = set()
    for row in rows:
        player = ball_player(row)
        if player is None:
            continue
        scheduled = tg.stamp(row["scheduled_at"])
        # Match the same local-date visibility as the existing daily hub.
        if scheduled <= now or tg.day(scheduled) != day or scheduled.astimezone(tg.TZ).date().isoformat() != day:
            continue
        identity = (str(row["event_id"]), str(player["id"]))
        if not all(identity):
            raise ValueError("Incomplete website ball identity")
        if identity in identities:
            raise ValueError("Duplicate ball player on same source event")
        identities.add(identity)
        confidence = row.get("projection_confidence")
        conf = tg.num(confidence)
        if conf is not None and (not math.isfinite(conf) or not 0.5 <= conf <= 1.0):
            conf = None
        selected.append({
            "event_id": identity[0], "selection_id": identity[1],
            "name": str(player["name"]).strip(),
            "scheduled_at": row["scheduled_at"], "confidence": conf,
        })
    return selected


def site_readback(url):
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", str(url)):
        raise ValueError("Production readback URL must be HTTPS origin")
    token = os.getenv("BLINQ_LIVE_WORKER_TOKEN") or ""
    if not token:
        raise RuntimeError("Existing worker readback token absent")
    req = urllib.request.Request(
        url + "/api/v1/internal/serving-readback",
        headers={"Accept": "application/json", "Cache-Control": "no-cache",
                 "X-Blinq-Worker-Token": token},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("Website readback unavailable")
        body = response.read(100001)
    if len(body) > 100000:
        raise RuntimeError("Website readback oversized")
    return json.loads(body)


def verify_same_website(snapshot, site, selected, now):
    day = tg.day(now)
    if (not isinstance(site, dict) or site.get("ok") is not True
            or site.get("schema") != 1 or site.get("ready") is not True
            or site.get("stale") is not False
            or site.get("betting_day") != day
            or not isinstance(snapshot.get("source_feed_generated_at"), str)
            or site.get("generated_at") != snapshot.get("source_feed_generated_at")):
        raise ValueError("Live website and confirmed ACE feed differ")
    counts = site.get("visible_counts")
    if (not isinstance(counts, dict)
            or type(counts.get("ace_picks")) is not int
            or counts["ace_picks"] < len(selected)):
        raise ValueError("Live ACES website section incomplete")
    return True


def render_messages(rows, now, footer):
    """The same header/date/compact-line/footer as the regular daily offer."""
    if not rows:
        return []
    header = [tg.HEADER, "📅 " + now.astimezone(tg.TZ).strftime("%d.%m.%Y"),
              "🎾 VIAC ES"]
    footer = tg.branded_footer(footer)
    pages = []
    current = []
    def page(lines):
        return "\n\n".join([*header, "\n".join(lines), footer])
    for row in rows:
        name = tg._compact_player_name(row["name"])
        time = tg.stamp(row["scheduled_at"]).astimezone(tg.TZ).strftime("%H:%M")
        confidence = row.get("confidence")
        suffix = f" | {confidence*100:.1f}%" if confidence is not None else ""
        line = f"🎾 | {name} | {time} | viac ES{suffix}"
        if len(page([*current, line]).encode("utf-16-le")) // 2 > 4096:
            if not current:
                raise RuntimeError("Website ball name exceeds Telegram limit")
            pages.append({"audience": "premium", "text": page(current)})
            current = [line]
        else:
            current.append(line)
    if current:
        pages.append({"audience": "premium", "text": page(current)})
    if any(len(p["text"].encode("utf-16-le")) // 2 > 4096 for p in pages):
        raise RuntimeError("Telegram message too large")
    return pages


def prepare(args):
    now = tg.stamp(args.now) if args.now else datetime.now(timezone.utc)
    day = tg.day(now)
    ident = "more-aces:" + day  # separate from regular bet and results ledgers
    state = tg.load(args.state)
    attempts = state.get("attempts")
    if not isinstance(attempts, dict) or state.get("schema") != 1:
        raise RuntimeError("Invalid private Telegram ledger")
    if ident in attempts:
        print(json.dumps({"status": "skipped", "reason": "already_reserved_or_sent", "day": day}))
        return
    original = attempts.get(day + ":daily:0620") or {}
    if (original.get("status") != "sent" or not original.get("message_ids")
            or not original.get("sent_at")):
        print(json.dumps({"status": "skipped", "reason": "regular_daily_offer_not_confirmed", "day": day}))
        return
    output = Path(args.output)
    snapshot = tg.snapshot(output / "assets")
    candidates = offered_rows(snapshot, now)
    readback = site_readback(args.api_url)
    verify_same_website(snapshot, readback, candidates, now)
    if not candidates:
        print(json.dumps({"status": "skipped", "reason": "no_future_ball_marked_aces", "day": day}))
        return
    messages = render_messages(candidates, now, tg.FOOTER)
    state["attempts"][ident] = {
        "status": "reserved", "betting_day": day, "reserved_at": now.isoformat(),
        "source": "website_aces_superiority_ball_v1",
        "website_generated_at": snapshot["generated_at"],
        "rows": candidates, "sha256": sha256(
            json.dumps(messages, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }
    tg.save(output / "messages.json", messages)
    tg.save(output / "state.json", state)
    (output / "ready").write_text(ident, encoding="utf-8")
    print(json.dumps({"status": "reserved", "day": day, "marked_players": len(candidates),
                      "messages": len(messages), "paid_provider_requests": 0, "cdb_writes": 0}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["prepare"])
    p.add_argument("--state", required=True)
    p.add_argument("--api-url", default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net")
    p.add_argument("--output", default="/tmp/blinq-telegram")
    p.add_argument("--now", default="")
    prepare(p.parse_args())
