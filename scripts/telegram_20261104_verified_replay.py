"""One-time, receipt-frozen Telegram 4 Nov settlement replay; no provider or CDB calls.

Only proven source-native match-status records from the pinned 5 Nov worker log
are considered, with the original immutable Telegram market/price contract.
Uses the existing Results grading and Telegram reservation/send machinery.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import telegram_daily_results as results
import telegram_offer_publisher as tg
from tbt.services.results_archive import settled_archive_candidates

DAY = "2026-11-04"
SOURCE_RUN = 41969752703
SOURCE_JOB = 127054985086
SOURCE_UPDATED = "2026-11-05T04:45:30.069667+00:00"
WITNESS = Path(__file__).with_name("telegram_20261104_verified_statuses.json")
REQUEST = Path(".github/telegram-20261104-verified-replay-request.json")


def verified_witness(sent: list[dict], payload: dict) -> dict:
    """Enforce unchanged six-event, pre-existing archived provider evidence."""
    aces = [x for x in sent if x.get("channel") == "aces"]
    if (payload.get("schema") != 1
            or payload.get("kind") != "read_only_provider_verified_match_status_witness"
            or payload.get("betting_day") != DAY
            or payload.get("source_run_id") != SOURCE_RUN
            or payload.get("source_job_id") != SOURCE_JOB
            or payload.get("source_updated_at") != SOURCE_UPDATED
            or len(aces) != 6 or len({str(x["event_id"]) for x in aces}) != 6
            or set(payload.get("statuses") or {}) != {str(x["event_id"]) for x in aces}):
        raise RuntimeError("Changed or incomplete exact source-native 4 Nov witness")
    for ref in aces:
        event = str(ref["event_id"])
        obs = payload["statuses"][event]
        if (not isinstance(obs, dict)
                or str(obs.get("status") or "") not in {"win", "loss", "void", "retired"}
                or str(obs.get("provider_status") or "") not in {
                    "finished ended", "finished retired", "finished cancelled"
                } or not isinstance(obs.get("projection_stats"), dict)):
            raise RuntimeError("Non-terminal or unverified 4 Nov event status " + event)
        p1, p2 = str(obs.get("provider_home_id") or ""), str(obs.get("provider_away_id") or "")
        if (not p1 or not p2 or p1 == p2
                or str(ref.get("selection_id") or "") not in {p1, p2}
                or str(obs.get("projection_stats_p1_id") or "") != p1
                or str(obs.get("projection_stats_p2_id") or "") != p2):
            raise RuntimeError("Unverified event/selection/player-stat identity " + event)
        checked = datetime.fromisoformat(str(obs.get("checked_at") or "").replace("Z", "+00:00"))
        if checked.tzinfo is None or not ("2026-11-04" <= checked.date().isoformat() <= "2026-11-05"):
            raise RuntimeError("Invalid contemporaneous provider observation " + event)
    return payload["statuses"]


def frozen_candidate(ref: dict, status: dict, issued: str, *, betting_day: str = DAY) -> dict:
    """Use canonical Results grader; do NOT calculate winners from the projection."""
    event, sel = str(ref.get("event_id") or ""), str(ref.get("selection_id") or "")
    line, odds, proj = tg.num(ref.get("market_line")), tg.num(ref.get("odds")), tg.num(ref.get("projection"))
    p1, p2 = str(status.get("provider_home_id") or ""), str(status.get("provider_away_id") or "")
    side = str(ref.get("projection_direction") or "").lower()
    expected = f"local-aces-ou-v1:{event}:{sel}:{side}:{line:.1f}" if line is not None else ""
    issued_dt = tg.stamp(issued)
    scheduled = tg.stamp(ref.get("scheduled_at"))
    if (
        not event or not sel or ref.get("market") != "aces" or ref.get("section") != "ace"
        or ref.get("channel") != "aces" or ref.get("price_basis") != tg.PRICE_BASIS
        or side not in {"over", "under"} or line is None or line <= 0
        or odds is None or odds <= 1 or proj is None or proj < 0
        or ref.get("publication_key") != expected
        or scheduled.tzinfo is None or issued_dt >= scheduled
        or scheduled.date().isoformat() != betting_day
        or sel not in {p1, p2} or p1 == p2
    ):
        raise RuntimeError("Immutable Telegram Aces O/U contract mismatch: " + event)
    pub = {
        "section": "ace", "market": "aces", "selection_id": sel,
        "publication_key": expected, "publication_status": "published",
        "price_contract": "player_total_ou", "ou_side": side,
        "market_line": line, "projection_scope": "player",
        "projection_metric": "aces", "selection": f"{ref.get('name') or sel} {side.title()} {line:.1f} Aces",
        "projection": proj, "issued_at": issued, "odds": odds,
        "price_status": "priced_projection", "price_basis": tg.PRICE_BASIS,
        "source": "frozen_confirmed_telegram_daily_receipt",
    }
    row = {
        "event_id": event, "scheduled_at": ref["scheduled_at"],
        "betting_day": betting_day, "selection_id": sel,
        "player1": {"id": p1, "name": ref.get("name") if sel == p1 else p1},
        "player2": {"id": p2, "name": ref.get("name") if sel == p2 else p2},
        "betting": {"selection_id": sel},
        "projection": proj, "market_publications": [pub],
    }
    feed = {"ace_picks": [row], "results": [], "generated_at": issued}
    rows = settled_archive_candidates(feed, {event: status})
    if len(rows) != 1 or rows[0].get("event_id") != event:
        raise RuntimeError("Canonical grader did not settle exact frozen Aces O/U " + event)
    graded = rows[0]["market_publications"][0]
    if graded.get("publication_key") != expected or not isinstance(graded.get("result"), dict):
        raise RuntimeError("Canonical Results grader changed original O/U identity")
    outcome = graded["result"]
    if (outcome.get("runtime_source") != "match_status_snapshot"
            or not (type(outcome.get("correct")) is bool or outcome.get("void") is True)):
        raise RuntimeError("Canonical grader did not provide final verified result")
    return {
        "event_id": event, "section": "ace", "market": "aces",
        "selection_id": sel, "publication_key": expected,
        "market_line": line, "projection_direction": side, "odds": odds,
        "price_status": "priced_projection", "result": outcome,
    }


def prepare(state: dict, archived: list[dict], witness: dict, config: dict, output: Path) -> dict:
    key = "results:" + DAY
    if key in (state.get("attempts") or {}):
        return {"status": "skipped", "reason": "results_already_reserved_or_sent", "day": DAY}
    sent = results.extract_sent(state, DAY)
    if len(sent) != 16 or sum(r.get("channel") == "aces" for r in sent) != 6:
        raise RuntimeError("Unexpected original confirmed 4 Nov Telegram selection cohort")
    statuses = verified_witness(sent, witness)
    issued = state["attempts"][DAY + ":daily:0620"].get("sent_at")
    if not issued or not isinstance(issued, str):
        raise RuntimeError("Missing confirmed original Telegram send timestamp")
    # Never rewrite or discard an existing verified archive outcome.
    replayed = list(archived)
    appended = []
    for ref in sent:
        if results.evaluate(ref, replayed)["status"] != "pending":
            continue
        if ref.get("channel") != "aces":
            raise RuntimeError("Missing non-Aces settlement: refusing partial report")
        entry = frozen_candidate(ref, statuses[ref["event_id"]], issued)
        if results.evaluate(ref, [entry])["status"] == "pending":
            raise RuntimeError("Frozen canonical Aces grade cannot satisfy exact issued bet")
        replayed.append(entry)
        appended.append(ref["event_id"])
    if not results.all_settled(sent, replayed):
        raise RuntimeError("Pending 4 Nov issued selections remain: no Telegram send")
    posts = results.combined_daily_report(sent, replayed, DAY, tg.branded_footer(config.get("footer")))
    if not posts or any(p.get("counts", {}).get("pending") for p in posts):
        raise RuntimeError("Invalid or incomplete 4 Nov report")
    for post in posts:
        post["audience"] = "elite"
    state = dict(state)
    state["attempts"] = dict(state["attempts"])
    now = datetime.now(timezone.utc).isoformat()
    state["attempts"][key] = {
        "status": "reserved", "reserved_at": now, "betting_day": DAY,
        "counts": {k: sum(p["counts"][k] for p in posts)
                   for k in ("won", "lost", "void", "pending")},
        "witness_run_id": SOURCE_RUN, "read_only_replayed_exact_aces": len(appended),
    }
    tg.save(output / "messages.json", [{"audience": p["audience"], "text": p["text"]} for p in posts])
    tg.save(output / "state.json", state)
    (output / "ready").write_text(key, encoding="utf-8")
    return {"status": "reserved", "day": DAY, "posts": len(posts),
            "verified_issued": len(sent), "replayed_exact_aces": appended,
            "counts": state["attempts"][key]["counts"], "paid_provider_requests": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare"])
    parser.add_argument("--state", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--config-url", required=True)
    parser.add_argument("--output", default="/tmp/blinq-telegram")
    args = parser.parse_args()
    expected = {"schema": 1, "day": DAY, "mode": "receipt-and-frozen-provider-status",
                "source_run_id": SOURCE_RUN, "paid_provider_requests": 0,
                "cdb_write": False, "results_archive_write": False,
                "telegram_delivery_authorized": True}
    if json.loads(REQUEST.read_text(encoding="utf-8")) != expected:
        raise RuntimeError("Unapproved or mutated 4 Nov recovery request")
    state = tg.load(args.state)
    witness = tg.load(WITNESS)
    archived = results.archive(args.api_url, DAY)
    cfg = tg.config(args.config_url)
    if not isinstance(state, dict) or not isinstance(state.get("attempts"), dict):
        raise RuntimeError("Invalid immutable Telegram ledger")
    outcome = prepare(state, archived, witness, cfg, Path(args.output))
    print("TELEGRAM_4NOV_FROZEN_RECOVERY " + json.dumps(outcome, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
