"""One-shot same-day ATP/WTA ESÁ + VIAC ES Telegram update from deployed issued website.

No new provider calls, no CDB writes, no change to previously issued bets.
Original daily and More Aces receipts remain immutable, and independently
confirmed new Aces tips are kept in the ordinary Results ledger for grading.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import telegram_offer_publisher as tg
import telegram_more_aces as more
from tbt.services.feed import main_tour_aces
from tbt.services.issued_authority import row_authority_key

DAY = "2026-11-10"
ORIGINAL_KEY = DAY + ":daily:0620"
ORIGINAL_MORE_KEY = "more-aces:" + DAY
UPDATE_KEY = DAY + ":daily:refresh-atp-wta-v1"
ORIGINAL_IDS = [752, 753]
ORIGINAL_MORE_IDS = [754]
ORIGINAL_SHA = "071b43ba673d8898dde6d93648daa4c130e7cb0d1e619361b8e34772b1db2616"
ORIGINAL_MORE_SHA = "2aebcd3d8eebedd75ee0053d0313e532d81e691bdee11f488cb95ebfaa7401ee"


def checked_original(state):
    attempts = state.get("attempts") if isinstance(state, dict) and state.get("schema") == 1 else None
    if not isinstance(attempts, dict):
        raise RuntimeError("Private Telegram ledger unavailable")
    old, old_more = attempts.get(ORIGINAL_KEY), attempts.get(ORIGINAL_MORE_KEY)
    for record, ids, digest in (
        (old, ORIGINAL_IDS, ORIGINAL_SHA),
        (old_more, ORIGINAL_MORE_IDS, ORIGINAL_MORE_SHA),
    ):
        if (not isinstance(record, dict) or record.get("status") != "sent"
                or record.get("message_ids") != ids or record.get("sha256") != digest):
            raise RuntimeError("Original 10 Nov Telegram receipts changed")
    rows = old.get("rows") or []
    old_aces = [r for r in rows if isinstance(r, dict) and r.get("channel") == "aces"]
    if (len(rows) != 12 or len(old_aces) != 8
            or len(old_more.get("rows") or []) != 8):
        raise RuntimeError("Unexpected original 10 Nov issued tips")
    identities = [(str(r.get("event_id")), str(r.get("selection_id"))) for r in old_aces]
    if len(set(identities)) != 8:
        raise RuntimeError("Ambiguous original Aces identities")
    if UPDATE_KEY in attempts:
        return attempts, old, old_aces, False
    return attempts, old, old_aces, True


def require_website(snapshot, website, now, old):
    if (snapshot.get("schema") != 1 or snapshot.get("confirmed_only") is not True
            or snapshot.get("betting_day") != DAY
            or tg.day(tg.stamp(snapshot["generated_at"])) != DAY
            or tg.stamp(snapshot["generated_at"]) > now
            or not isinstance(snapshot.get("source_feed_generated_at"), str)
            or snapshot["source_feed_generated_at"] == old.get("source_feed_generated_at")):
        raise RuntimeError("No newly confirmed current-day offer generation")
    if (not isinstance(website, dict) or website.get("ok") is not True
            or website.get("schema") != 1 or website.get("ready") is not True
            or website.get("stale") is not False
            or website.get("betting_day") != DAY
            or website.get("generated_at") != snapshot["source_feed_generated_at"]):
        raise RuntimeError("Production website is not serving the exact refreshed generation")
    authority = (website.get("offer_authority_keys") or {}).get("aces")
    if not isinstance(authority, list) or len(authority) != len(set(authority)):
        raise RuntimeError("Exact production Aces issue authority unavailable")
    count = (website.get("visible_counts") or {}).get("ace_picks")
    if type(count) is not int or count < 0:
        raise RuntimeError("Missing independently verified website Aces count")
    return set(authority), count


def future_picks(snapshot, website, now, original_aces, old):
    authorized, website_count = require_website(snapshot, website, now, old)
    config = {"sections": {"top": False, "value": False, "aces": True},
              "free_top_pick": False, "include_started": False, "max_per_section": 0,
              "aces_ou_only": True, "layout": "combined",
              "show_odds": True, "show_probability": False}
    regular = tg.select_groups(snapshot, config, now).get("aces", [])
    ball = more.offered_rows(snapshot, now)
    prior_by_event = {str(row["event_id"]): row for row in original_aces}
    selected = []
    references = []
    seen = set()
    for row in regular:
        if not main_tour_aces(row):
            raise RuntimeError("Excluded tournament leaked into Aces")
        key = row_authority_key(row, "ace_picks")
        if key not in authorized:
            raise RuntimeError("Fresh Aces selection missing exact issued website authority")
        reference = tg.result_reference(row, "aces")
        match = str(reference["event_id"])
        if match in seen:
            raise RuntimeError("Multiple fresh Aces contracts for one event")
        seen.add(match)
        original = prior_by_event.get(match)
        if original and not tg._same_frozen_selection(reference, original):
            raise RuntimeError("Refreshed Aces conflicts with a previously issued contract")
        selected.append(row)
        references.append(reference)
    if len(selected) > website_count or len(ball) > website_count:
        raise RuntimeError("Fresh Telegram selections exceed exact website offer")
    if len({(str(r["event_id"]), str(r["selection_id"])) for r in ball}) != len(ball):
        raise RuntimeError("Duplicate Most Aces player")
    for bet in ball:
        matching = [
            row for row in snapshot.get("ace_picks") or []
            if isinstance(row, dict) and row.get("market") == "aces"
            and str(row.get("event_id")) == str(bet["event_id"])
            and str(row.get("scheduled_at")) == str(bet["scheduled_at"])
            and (player := more.ball_player(row)) is not None
            and str(player["id"]) == str(bet["selection_id"])
            and main_tour_aces(row)
        ]
        if len(matching) != 1 or row_authority_key(matching[0], "ace_picks") not in authorized:
            raise RuntimeError("Most Aces is not an exact issued website ball signal")
    return config, selected, references, ball


def prepare(args):
    now = tg.stamp(args.now) if args.now else datetime.now(timezone.utc)
    if tg.day(now) != DAY or now.astimezone(tg.TZ).date().isoformat() != DAY:
        print(json.dumps({"status": "skipped", "reason": "one_day_update_expired"}))
        return
    state = tg.load(args.state)
    attempts, old, old_aces, available = checked_original(state)
    if not available:
        print(json.dumps({"status": "skipped", "reason": "already_reserved_or_sent"}))
        return
    output = Path(args.output)
    snapshot = tg.snapshot(output / "assets")
    website = more.site_readback(args.api_url)
    config, regular, references, ball = future_picks(snapshot, website, now, old_aces, old)
    if not regular and not ball:
        print(json.dumps({"status": "skipped", "reason": "no_future_atp_wta_aces"}))
        return
    messages = []
    aces = tg.messages({**snapshot, "ace_picks": regular}, config, now)
    for item in aces:
        item["text"] = "🔄 AKTUALIZOVANÁ PONUKA · ATP/WTA ESÁ\n\n" + item["text"]
        messages.append(item)
    for item in more.render_messages(ball, now, tg.FOOTER):
        item["text"] = "🔄 AKTUALIZOVANÁ PONUKA · ATP/WTA VIAC ES\n\n" + item["text"]
        messages.append(item)
    if any(len(m["text"].encode("utf-16-le")) // 2 > 4096 for m in messages):
        raise RuntimeError("Updated Telegram message is too large")
    if any(item.get("audience") != "premium" for item in messages):
        raise RuntimeError("Unexpected Telegram recipient")
    oldrefs = {(str(row.get("event_id")), str(row.get("selection_id")),
                str(row.get("publication_key")), str(row.get("market_line")),
                str(row.get("projection_direction"))) for row in old_aces}
    additional = sum(
        (str(row.get("event_id")), str(row.get("selection_id")),
         str(row.get("publication_key")), str(row.get("market_line")),
         str(row.get("projection_direction"))) not in oldrefs
        for row in references
    )
    attempts[UPDATE_KEY] = {
        "status": "reserved", "reserved_at": now.isoformat(),
        "kind": "issued-same-day-atp-wta-aces-refresh-v1",
        "betting_day": DAY,
        "original_telegram_ids": ORIGINAL_IDS + ORIGINAL_MORE_IDS,
        "source_feed_generated_at": snapshot["source_feed_generated_at"],
        "rows": references,  # Only actual O/U bets are eligible for Results.
        "most_aces_signals": ball,  # Separate ball signal; never an invented O/U.
        "counts": {"aces": len(regular), "more_aces": len(ball),
                   "net_new_issued_aces": additional},
        "paid_provider_requests": 0, "cdb_writes": 0,
        "sha256": sha256(json.dumps(messages, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }
    tg.save(output / "messages.json", messages)
    tg.save(output / "state.json", {**state, "attempts": attempts})
    output.mkdir(parents=True, exist_ok=True)
    (output / "ready").write_text(UPDATE_KEY, encoding="utf-8")
    print(json.dumps({"status": "reserved", "id": UPDATE_KEY, "messages": len(messages),
                      "aces": len(regular), "more_aces": len(ball),
                      "net_new_issued_aces": additional, "paid_provider_requests": 0}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare"])
    p.add_argument("--state", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--output", default="/tmp/blinq-telegram")
    p.add_argument("--now", default="")
    prepare(p.parse_args())
