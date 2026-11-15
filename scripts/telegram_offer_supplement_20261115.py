"""One-time, confirmed-only supplemental Telegram delivery for 15 Nov 2026.

The morning batch already sent one TOP; only subsequently issued TOP/ESÁ
may be sent here. No rewriting of Telegram receipts, private prediction
ledger, daily snapshot, or betting outcomes. Never reissue a past pick.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import telegram_offer_publisher as tg

REVISION = "top-aces-added-v1"
BETTING_DAY = "2026-11-15"
SECTIONS = ("top", "value", "aces")


def identity(ref):
    return (
        str(ref.get("channel") or ""),
        str(ref.get("event_id") or ""),
        str(ref.get("market") or ""),
        str(ref.get("selection_id") or ""),
    )


def unsent_rows(groups, attempts, *, betting_day):
    """Return only newly issued future picks; never resend a reserved identity."""
    prior = {}
    for key, attempt in attempts.items():
        if not key.startswith(betting_day + ":") or not isinstance(attempt, dict):
            continue
        if attempt.get("status") not in ("sent", "reserved"):
            continue
        for previous in attempt.get("rows") or []:
            if not isinstance(previous, dict):
                raise ValueError("Invalid original Telegram receipt row")
            signature = identity(previous)
            if signature in prior and not tg._same_frozen_selection(previous, prior[signature]):
                raise RuntimeError("Conflicting original Telegram pick receipts")
            prior[signature] = previous

    new = {section: [] for section in SECTIONS}
    refs = []
    seen = set()
    for section in SECTIONS:
        for row in groups.get(section) or []:
            frozen = tg.result_reference(row, section)
            signature = identity(frozen)
            if signature in seen:
                raise RuntimeError("Duplicate supplemental Telegram identity")
            seen.add(signature)
            previous = prior.get(signature)
            if previous is not None:
                # The existing message is immutable. Never send a new quote or
                # changed selection for the same published Telegram identity.
                continue
            refs.append(frozen)
            new[section].append(row)
    return new, refs


def prepare(*, state_path, output, config_url, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware current time required")
    today = tg.day(now)
    if today != BETTING_DAY:
        raise RuntimeError("One-time supplementary Telegram request is expired")
    state = tg.load(state_path)
    attempts = state.get("attempts")
    if not isinstance(attempts, dict):
        raise RuntimeError("Missing durable Telegram receipt ledger")
    original = attempts.get(tg._daily_id(now))
    if (not isinstance(original, dict) or original.get("status") != "sent"
            or not original.get("message_ids") or not original.get("rows")):
        raise RuntimeError("Original morning Telegram delivery is not confirmed")

    ident = today + ":supplement:" + REVISION
    if ident in attempts:
        print(json.dumps({"status": "skipped", "reason": "supplement_reserved_or_sent", "id": ident}))
        return None

    out = Path(output)
    confirmed = tg.snapshot(out / "assets")
    if confirmed.get("confirmed_only") is not True or confirmed.get("betting_day") != today:
        raise RuntimeError("Only today's confirmed issued snapshot is sendable")
    # The four user-observed picks must really exist in the private issued
    # snapshot, not merely in the public prediction candidate.
    if len(confirmed.get("top_daily_picks") or []) < 2:
        raise RuntimeError("Confirmed snapshot has fewer than two TOP picks")
    ace_rows = [r for r in (confirmed.get("ace_picks") or [])
                if isinstance(r, dict) and str(r.get("market") or "") == "aces"]
    if len(ace_rows) < 2:
        raise RuntimeError("Confirmed snapshot has fewer than two issued ESÁ O/U picks")

    tg.verify_prepared_site(confirmed, config_url, now)
    settings = {
        **tg.config(config_url),
        "enabled": True,
        "sections": {name: True for name in SECTIONS},
        "layout": "combined",
        "max_per_section": 0,
        "free_top_pick": False,
        "include_started": False,
        "aces_ou_only": True,
    }
    original_groups = tg.select_groups(confirmed, settings, now)
    new, frozen = unsent_rows(original_groups, attempts, betting_day=today)
    if not frozen:
        print(json.dumps({"status": "skipped", "reason": "no_new_future_confirmed_picks", "id": ident}))
        return None
    # Market isolation: Viac Es is never transformed into ESÁ O/U.
    if any(r["market"] not in {"match_winner", "aces"} for r in frozen):
        raise RuntimeError("Supplement cannot include other markets")
    filtered = {
        **confirmed,
        "top_daily_picks": new["top"],
        "value_picks": new["value"],
        "ace_picks": new["aces"],
    }
    messages = tg.messages(filtered, settings, now)
    if not messages or any(m.get("audience") != "premium" for m in messages):
        raise RuntimeError("No safe premium supplemental Telegram message")
    # messages() may reapply _daily_rows; require byte-exact selection parity.
    formatted_groups = tg.select_groups(filtered, settings, now)
    checked_refs = [
        tg.result_reference(row, section)
        for section in SECTIONS
        for row in (formatted_groups.get(section) or [])
    ]
    if checked_refs != frozen:
        raise RuntimeError("Supplemental Telegram message changed exact issued picks")

    record = {
        "status": "reserved",
        "reserved_at": now.isoformat(),
        "source_feed_generated_at": confirmed.get("source_feed_generated_at"),
        "snapshot_sha256": hashlib.sha256(json.dumps(
            confirmed, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "rows": frozen,
        "sha256": hashlib.sha256(json.dumps(
            messages, ensure_ascii=False).encode()).hexdigest(),
    }
    updated = dict(state)
    updated["attempts"] = {**attempts, ident: record}
    tg.save(out / "state.json", updated)
    tg.save(out / "messages.json", messages)
    (out / "ready").write_text(ident, encoding="utf-8")
    result = {
        "status": "reserved",
        "id": ident,
        "new_top": len(new["top"]),
        "new_aces": len(new["aces"]),
        "new_value": len(new["value"]),
        "messages": len(messages),
    }
    print(json.dumps(result))
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", required=True)
    p.add_argument("--output", default="/tmp/blinq-telegram")
    p.add_argument("--config-url", required=True)
    args = p.parse_args()
    prepare(state_path=args.state, output=args.output, config_url=args.config_url)


if __name__ == "__main__":
    main()
