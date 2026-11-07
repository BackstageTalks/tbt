"""One-time Telegram 5 Nov Results from frozen receipts and pinned provider statuses.

Uses the existing exact market grader, read-only verified archive and private
Telegram send/receipt ledger. Never writes CDB, model, odds or source archive.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import telegram_daily_results as results
import telegram_offer_publisher as tg
from telegram_20261104_verified_replay import frozen_candidate

DAY = "2026-11-05"
SOURCE_RUN = 42164364859
SOURCE_JOB = 127717246453
SOURCE_UPDATED = "2026-11-06T04:45:30.742189+00:00"
WITNESS = Path(__file__).with_name("telegram_20261105_verified_statuses.json")
REQUEST = Path(".github/telegram-20261105-verified-replay-request.json")


def verified_witness(sent: list[dict], payload: dict) -> dict:
    """Accept only seven exact source-native terminal events from the pinned log."""
    aces = [row for row in sent if row.get("channel") == "aces"]
    event_ids = {str(ref.get("event_id") or "") for ref in aces}
    if (
        payload.get("schema") != 1
        or payload.get("kind") != "read_only_provider_verified_match_status_witness"
        or payload.get("betting_day") != DAY
        or payload.get("source_run_id") != SOURCE_RUN
        or payload.get("source_job_id") != SOURCE_JOB
        or payload.get("source_updated_at") != SOURCE_UPDATED
        or len(aces) != 7 or len(event_ids) != 7
        or set(payload.get("statuses") or {}) != event_ids
    ):
        raise RuntimeError("Changed or incomplete exact 5 Nov source-native witness")
    source_time = tg.stamp(SOURCE_UPDATED)
    for ref in aces:
        event = str(ref["event_id"])
        obs = payload["statuses"][event]
        if (
            not isinstance(obs, dict)
            or obs.get("status") not in {"win", "loss"}
            or obs.get("provider_status") != "finished ended"
        ):
            raise RuntimeError("Missing verified terminal outcome: " + event)
        home = str(obs.get("provider_home_id") or "")
        away = str(obs.get("provider_away_id") or "")
        if (
            not home or not away or home == away
            or str(ref.get("selection_id") or "") not in {home, away}
            or str(obs.get("projection_stats_p1_id") or "") != home
            or str(obs.get("projection_stats_p2_id") or "") != away
        ):
            raise RuntimeError("Unverified provider/player/stat identity: " + event)
        stats = obs.get("projection_stats")
        if not isinstance(stats, dict):
            raise RuntimeError("Missing provider stat evidence: " + event)
        for side in ("p1_aces", "p2_aces"):
            count = stats.get(side)
            if type(count) is not int or count < 0:
                raise RuntimeError("Unverified source-native player Ace count: " + event)
        checked = tg.stamp(obs.get("checked_at"))
        stat_checked = tg.stamp(obs.get("projection_stats_checked_at"))
        if not (
            "2026-11-05" <= checked.date().isoformat() <= "2026-11-06"
            and checked <= stat_checked <= source_time
        ):
            raise RuntimeError("Noncontemporaneous provider evidence: " + event)
    return payload["statuses"]


def prepare(state: dict, archived: list[dict], witness: dict, config: dict, output: Path) -> dict:
    key = "results:" + DAY
    if key in (state.get("attempts") or {}):
        return {"status": "skipped", "reason": "results_already_reserved_or_sent", "day": DAY}
    sent = results.extract_sent(state, DAY)
    if len(sent) != 13 or sum(ref.get("channel") == "aces" for ref in sent) != 7:
        raise RuntimeError("Unexpected immutable 5 Nov issued Telegram cohort")
    statuses = verified_witness(sent, witness)
    issued = (state.get("attempts") or {}).get(DAY + ":daily:0620", {}).get("sent_at")
    if not issued:
        raise RuntimeError("Missing exact original 5 Nov Telegram sent timestamp")
    # A source-native witness cannot substitute for the persisted archive.
    # Never send a report built from temporary reconstructed rows.
    if not results.all_settled(sent, archived):
        raise RuntimeError("Exact 5 Nov results must already be durable in the verified archive")
    replayed = list(archived)
    appended = []
    posts = results.combined_daily_report(sent, replayed, DAY, tg.branded_footer(config.get("footer")))
    if not posts or any(post.get("counts", {}).get("pending") for post in posts):
        raise RuntimeError("Incomplete 5 Nov ELITE Results: no Telegram send")
    for post in posts:
        post["audience"] = "elite"
    reserved = dict(state)
    reserved["attempts"] = dict(state["attempts"])
    reserved["attempts"][key] = {
        "status": "reserved",
        "reserved_at": datetime.now(timezone.utc).isoformat(),
        "betting_day": DAY,
        "counts": {kind: sum(post["counts"][kind] for post in posts)
                   for kind in ("won", "lost", "void", "pending")},
        "witness_run_id": SOURCE_RUN,
        "read_only_replayed_exact_aces": len(appended),
    }
    output.mkdir(parents=True, exist_ok=True)
    tg.save(output / "messages.json", [
        {"audience": post["audience"], "text": post["text"]} for post in posts
    ])
    tg.save(output / "state.json", reserved)
    (output / "ready").write_text(key, encoding="utf-8")
    return {
        "status": "reserved", "day": DAY, "posts": len(posts),
        "verified_issued": len(sent), "replayed_exact_aces": appended,
        "counts": reserved["attempts"][key]["counts"],
        "paid_provider_requests": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare"])
    parser.add_argument("--state", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--config-url", required=True)
    parser.add_argument("--output", default="/tmp/blinq-telegram")
    args = parser.parse_args()
    expected = {
        "schema": 1, "day": DAY, "mode": "receipt-and-frozen-provider-status",
        "source_run_id": SOURCE_RUN, "source_job_id": SOURCE_JOB,
        "source_updated_at": SOURCE_UPDATED, "paid_provider_requests": 0,
        "cdb_write": False, "results_archive_write": False,
        "telegram_delivery_authorized": True,
    }
    if json.loads(REQUEST.read_text(encoding="utf-8")) != expected:
        raise RuntimeError("Unapproved or mutated 5 Nov Telegram Results request")
    if datetime.now(timezone.utc).astimezone(tg.TZ).date().isoformat() != "2026-11-06":
        raise RuntimeError("5 Nov Results replay authorization expired")
    state = tg.load(args.state)
    witness = tg.load(WITNESS)
    archived = results.archive(args.api_url, DAY)
    config = tg.config(args.config_url)
    if not isinstance(state, dict) or not isinstance(state.get("attempts"), dict):
        raise RuntimeError("Invalid immutable Telegram ledger")
    outcome = prepare(state, archived, witness, config, Path(args.output))
    print("TELEGRAM_5NOV_VERIFIED_RESULTS " + json.dumps(outcome, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
