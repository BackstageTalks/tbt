"""Explicit one-time reissue of an already delivered, verified Telegram results report.

No CDB writes, no paid tennis API calls, no changes to canonical results delivery.
Preserve original settlement source and reserve in the independent repost ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import telegram_daily_results as results
import telegram_offer_publisher as tg


def prepare(args):
    day = args.day
    revision = args.revision
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Invalid betting day")
    datetime.fromisoformat(day)
    if not re.fullmatch(r"[A-Za-z0-9-]{8,48}", revision):
        raise ValueError("Invalid resend revision")

    state = tg.load(args.state)
    attempts = state.get("attempts")
    reposts = state.get("reposts") or {}
    if not isinstance(attempts, dict) or not isinstance(reposts, dict):
        raise RuntimeError("Invalid private Telegram ledger")
    original = attempts.get("results:" + day)
    if not isinstance(original, dict) or original.get("status") != "sent":
        raise RuntimeError("Original verified results not sent")
    original_receipts = original.get("message_ids")
    if not isinstance(original_receipts, list) or not original_receipts or not all(
        isinstance(x, int) and x > 0 for x in original_receipts
    ):
        raise RuntimeError("Original Telegram results lack confirmed receipts")
    key = f"results-reissue:{day}:{revision}"
    if key in reposts:
        print(json.dumps({"status": "skipped", "reason": "already_reserved_or_sent", "key": key}))
        return

    original_rows = results.extract_sent(state, day)
    if not original_rows:
        raise RuntimeError("Missing original sent selection identities")
    verified = results.archive(args.api_url, day)
    if not results.all_settled(original_rows, verified):
        raise RuntimeError("Never reissue unresolved results")

    cfg = tg.config(args.config_url)
    posts = results.combined_daily_report(
        original_rows, verified, day, tg.branded_footer(cfg.get("footer"))
    )
    if len(posts) != len(original_receipts):
        raise RuntimeError("Results reissue differs from original page count")
    counts = {name: sum(p["counts"][name] for p in posts)
              for name in ("won", "lost", "void", "pending")}
    if counts != original.get("counts"):
        raise RuntimeError("Verified results differ from the originally sent totals")
    for post in posts:
        if post.get("audience") != "premium":
            raise RuntimeError("Unexpected results audience")
        if "📊 Denný súhrn" in post["text"] or "TOP · WIN" in post["text"]:
            raise RuntimeError("Obsolete results summary still present")
        post["audience"] = "elite"

    outbound = [{"audience": p["audience"], "text": p["text"]} for p in posts]
    serialized = json.dumps(outbound, ensure_ascii=False)
    reposts[key] = {
        "status": "reserved",
        "reserved_at": datetime.now(timezone.utc).isoformat(),
        "kind": "verified-results-format-reissue",
        "source_key": "results:" + day,
        "source_message_ids": list(original_receipts),
        "counts": counts,
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }
    output = Path(args.output)
    tg.save(output / "messages.json", outbound)
    tg.save(output / "state.json", {**state, "reposts": reposts})
    (output / "ready").write_text(key, encoding="utf-8")
    print(json.dumps({"status": "reserved", "key": key, "messages": len(outbound), "counts": counts}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare"])
    parser.add_argument("--day", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--config-url", required=True)
    parser.add_argument("--state", default=".private-telegram/ops/telegram-bot-state.json")
    parser.add_argument("--output", default="/tmp/blinq-telegram")
    args = parser.parse_args()
    prepare(args)
