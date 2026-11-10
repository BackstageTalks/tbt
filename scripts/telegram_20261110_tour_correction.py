"""One-shot 10 Nov Telegram tour correction, never a replacement bet or Results write.

Build from the same confirmed private offer and production website read-back.
Preserve every originally issued wager, its price, historical grade and IDs.
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
DAILY = DAY + ":daily:0620"
MORE = "more-aces:" + DAY
CORRECTION = DAY + ":repost:atp-wta-tour-correction-v1"
DAILY_IDS = [752, 753]
MORE_IDS = [754]
DAILY_HASH = "071b43ba673d8898dde6d93648daa4c130e7cb0d1e619361b8e34772b1db2616"
MORE_HASH = "2aebcd3d8eebedd75ee0053d0313e532d81e691bdee11f488cb95ebfaa7401ee"


def confirmed_originals(state):
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise RuntimeError("Invalid Telegram ledger")
    attempts = state.get("attempts")
    if not isinstance(attempts, dict):
        raise RuntimeError("Missing Telegram send receipts")
    regular = attempts.get(DAILY)
    leader = attempts.get(MORE)
    if not isinstance(regular, dict) or not isinstance(leader, dict):
        raise RuntimeError("Missing 10 Nov original send receipts")
    for record, ids, digest in ((regular, DAILY_IDS, DAILY_HASH), (leader, MORE_IDS, MORE_HASH)):
        if (record.get("status") != "sent" or
                record.get("message_ids") != ids or
                record.get("sha256") != digest):
            raise RuntimeError("The issued Telegram receipt has changed")
    regular_aces = [row for row in regular.get("rows") or []
                    if isinstance(row, dict) and row.get("channel") == "aces"]
    leader_rows = leader.get("rows")
    if len(regular_aces) != 8 or not isinstance(leader_rows, list) or len(leader_rows) != 8:
        raise RuntimeError("Original 10 Nov ESÁ / VIAC ES count changed")
    keys = [(str(x.get("event_id") or ""), str(x.get("selection_id") or "")) for x in regular_aces]
    other_keys = [(str(x.get("event_id") or ""), str(x.get("selection_id") or "")) for x in leader_rows]
    if (any(not all(pair) for pair in keys)
            or len(set(keys)) != 8 or len(set(other_keys)) != 8 or set(keys) != set(other_keys)):
        raise RuntimeError("Original ESÁ and VIAC ES identities are inconsistent")
    return regular_aces, leader_rows


def classify_original_rows(original, source_rows):
    if not isinstance(source_rows, list):
        raise RuntimeError("Confirmed source lacks ESÁ rows")
    matched = []
    for receipt in original:
        matches = [
            row for row in source_rows
            if isinstance(row, dict) and row.get("market") == "aces"
            and str(row.get("event_id") or "") == str(receipt.get("event_id") or "")
            and str(row.get("selection_id") or "") == str(receipt.get("selection_id") or "")
            and str(row.get("scheduled_at") or "") == str(receipt.get("scheduled_at") or "")
        ]
        if len(matches) != 1:
            raise RuntimeError("Original sent ESÁ not uniquely linked to confirmed pre-match offer")
        row = matches[0]
        if not tg._same_frozen_selection(tg.result_reference(row, "aces"), receipt):
            raise RuntimeError("Original issued Aces contract differs from confirmed offer")
        matched.append((receipt, row))
    return matched


def verified_production(snapshot, readback, matching):
    if (snapshot.get("confirmed_only") is not True
            or snapshot.get("betting_day") != DAY
            or readback.get("ok") is not True
            or readback.get("ready") is not True
            or readback.get("stale") is not False
            or readback.get("betting_day") != DAY
            or readback.get("generated_at") != snapshot.get("source_feed_generated_at")):
        raise RuntimeError("Live website and original confirmed generation are not identical")
    published = (readback.get("offer_authority_keys") or {}).get("aces")
    if not isinstance(published, list):
        raise RuntimeError("Exact website authority hashes missing")
    visible_keys = set(published)
    if len(visible_keys) != len(published):
        raise RuntimeError("Duplicate website issue hashes")
    for _, row in matching:
        if main_tour_aces(row) and row_authority_key(row, "ace_picks") not in visible_keys:
            raise RuntimeError("Eligible original ESÁ is not an issued website row")


def build_notice(matching):
    eligible = [receipt for receipt, row in matching if main_tour_aces(row)]
    ignored = len(matching) - len(eligible)
    names = "\n".join("• " + str(row.get("name") or row.get("selection_id")) for row in eligible)
    if not names:
        names = "Žiadny z pôvodných tipov nevyhovuje filtru."
    body = (
        "🎾 BlinQ | OPRAVA AKTÍVNEJ PONUKY – 10. 11.\n\n"
        "ESÁ aj VIAC ES: iba hlavný okruh ATP/WTA. "
        "Challenger, ITF, Futures a WTA 125 sa už do aktívnej ponuky nezaraďujú.\n\n"
        f"Z pôvodných 8 ESÁ/VIAC ES párov spĺňa nové pravidlo {len(eligible)}; "
        f"mimo hlavného okruhu je {ignored}.\n"
        f"ATP/WTA z pôvodnej ponuky:\n{names}\n\n"
        "Toto je upresnenie filtra, NIE nová stávka ani zmena pôvodných kurzov. "
        "Už vydané tipy ostávajú v historickej evidencii a budú posúdené "
        "podľa pôvodných pravidiel. Web a nové telegramové vydania používajú "
        "rovnaké ATP/WTA pravidlo.\n\n"
        + tg.branded_footer()
    )
    if len(body) > 3900:
        raise RuntimeError("Tour correction exceeds Telegram text size")
    return body, {"original": len(matching), "eligible_main_tour": len(eligible), "off_tour": ignored}


def prepare(args):
    now = tg.stamp(args.now) if args.now else datetime.now(timezone.utc)
    if tg.day(now) != DAY or now.astimezone(tg.TZ).date().isoformat() != DAY:
        print(json.dumps({"status": "skipped", "reason": "correction_day_expired"}))
        return
    state = tg.load(args.state)
    reposts = state.get("reposts") or {}
    if not isinstance(reposts, dict):
        raise RuntimeError("Invalid correction ledger")
    if CORRECTION in reposts:
        print(json.dumps({"status": "skipped", "reason": "already_reserved_or_sent"}))
        return
    originals, _ = confirmed_originals(state)
    dest = Path(args.output)
    snapshot = tg.snapshot(dest / "assets")
    matching = classify_original_rows(originals, snapshot.get("ace_picks"))
    website = more.site_readback(args.api_url)
    verified_production(snapshot, website, matching)
    text, counts = build_notice(matching)
    messages = [{"audience": "elite", "text": text}]
    now_iso = now.isoformat()
    reposts[CORRECTION] = {
        "status": "reserved", "kind": "issued-tour-scope-correction-only",
        "betting_day": DAY, "reserved_at": now_iso,
        "source_message_ids": DAILY_IDS + MORE_IDS,
        "counts": counts, "paid_provider_requests": 0, "cdb_writes": 0,
        "source_feed_generated_at": snapshot["source_feed_generated_at"],
        "sha256": sha256(json.dumps(messages, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }
    tg.save(dest / "messages.json", messages)
    tg.save(dest / "state.json", {**state, "reposts": reposts})
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "ready").write_text(CORRECTION, encoding="utf-8")
    print(json.dumps({"status": "reserved", "message_count": 1, **counts,
                      "paid_provider_requests": 0, "cdb_writes": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare"])
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", default="/tmp/blinq-telegram")
    parser.add_argument("--now", default="")
    prepare(parser.parse_args())
