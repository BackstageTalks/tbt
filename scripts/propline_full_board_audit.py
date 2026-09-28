#!/usr/bin/env python3
"""One-shot read-only audit of ALL current PropLine tennis fixtures.

Unlike the normal production fallback (which only queries matches that can be
matched safely to BlinQ model fixtures), this audits the entire PropLine board.
No Tennis RapidAPI requests, model changes, feed/ledger writes or new picks.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

from release_store import ReleaseStore
from tbt.services.propline_live import (
    PropLineClient, _events, _markets, _match_board, _name, _price, _when,
    KEYS, METRIC,
)

MAX_CALLS = 400
DAILY_RESERVE = 150


def complete_market_pairs(book: dict, requested: set[str]) -> dict[str, list[dict]]:
    """Validate complete sides on the same exact bookmaker, market and line.

    Player props require the same named player, rather than relying on a
    potentially unmatched BlinQ fixture. Returns a sample of actual prices.
    """
    found: dict[str, list[dict]] = {}
    for market in book.get("markets") or []:
        if not isinstance(market, dict):
            continue
        key = str(market.get("key") or "")
        if key not in requested:
            continue
        groups: dict[tuple[str, float], dict[str, float]] = {}
        for outcome in market.get("outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            side = _name(outcome.get("name"))
            if side not in ("over", "under"):
                continue
            try:
                line = float(outcome.get("point"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(line):
                continue
            metric = METRIC[key]
            if metric == "games" and not (8 <= line <= 80):
                continue
            if metric == "sets" and not (1.5 <= line <= 5.5):
                continue
            if metric == "aces" and not (0.5 <= line <= 40.5):
                continue
            if metric == "double_faults" and not (0.5 <= line <= 20.5):
                continue
            player = str(outcome.get("description") or "").strip() if metric in ("aces", "double_faults") else ""
            if metric in ("aces", "double_faults") and not player:
                continue
            price = _price(outcome.get("price"))
            if price is None:
                continue
            groups.setdefault((_name(player), line), {}).setdefault(side, price)
        for (player, line), sides in groups.items():
            if set(sides) == {"over", "under"}:
                found.setdefault(key, []).append({
                    "player": player or None, "line": line,
                    "over": sides["over"], "under": sides["under"],
                })
    return found


def scan_board(client: PropLineClient, *, now: datetime, known_predictions: list[dict]) -> dict:
    report = {
        "created_at_utc": now.isoformat(), "mode": "read_only_full_board_once",
        "events_on_board": 0, "eligible_future": 0, "matched_blinq": 0,
        "events_queried": 0, "market_list_requests": 0,
        "odds_requests": 0, "events_with_target_market": 0,
        "events_without_target_market": 0,
        "listed": {metric: 0 for metric in ("aces", "double_faults", "games", "sets")},
        "priced": {metric: 0 for metric in ("aces", "double_faults", "games", "sets")},
        "bookmakers": {metric: {} for metric in ("aces", "double_faults", "games", "sets")},
        "listed_market_keys": {}, "samples": {metric: [] for metric in ("aces", "double_faults", "games", "sets")},
        "errors": 0, "api_calls": 0, "provider_remaining": None,
        "stopped": None, "per_event": [],
    }
    try:
        board = _events(client.get("/sports/tennis/events"))
    except (RuntimeError, ValueError) as exc:
        report["errors"] += 1
        report["stopped"] = str(exc)
        report["api_calls"] = client.calls
        report["provider_remaining"] = client.remaining
        return report
    report["events_on_board"] = len(board)
    eligible = sorted(
        (e for e in board if str(e.get("id") or "").isdigit()
         and (dt := _when(e.get("commence_time"))) is not None and dt > now),
        key=lambda e: (_when(e["commence_time"]), str(e["id"])),
    )
    report["eligible_future"] = len(eligible)
    pairs = _match_board(known_predictions, eligible, now)
    matched_ids = {str(event["id"]) for _, event in pairs}
    report["matched_blinq"] = len(matched_ids)
    for event in eligible:
        if client.calls >= client.max_calls:
            report["stopped"] = "explicit_call_cap"
            break
        if client.remaining is not None and client.remaining < client.min_remaining + 2:
            report["stopped"] = "provider_quota_reserve"
            break
        eid = str(event["id"])
        record = {
            "provider_event_id": eid,
            "start": event.get("commence_time"),
            "player1": event.get("home_team"),
            "player2": event.get("away_team"),
            "matched_blinq": eid in matched_ids,
            "listed": [], "priced": [], "error": None,
        }
        report["events_queried"] += 1
        try:
            available = _markets(client.get(f"/sports/tennis/events/{eid}/markets"))
            report["market_list_requests"] += 1
            for key in available:
                report["listed_market_keys"][key] = report["listed_market_keys"].get(key, 0) + 1
            wanted = set(KEYS).intersection(available)
            listed = {METRIC[key] for key in wanted}
            record["listed"] = sorted(listed)
            for metric in listed:
                report["listed"][metric] += 1
            if not wanted:
                report["events_without_target_market"] += 1
            else:
                report["events_with_target_market"] += 1
                if client.calls >= client.max_calls:
                    report["stopped"] = "explicit_call_cap"
                elif client.remaining is not None and client.remaining < client.min_remaining + 1:
                    report["stopped"] = "provider_quota_reserve"
                else:
                    data = client.get(f"/sports/tennis/events/{eid}/odds",
                                      {"markets": ",".join(sorted(wanted))})
                    report["odds_requests"] += 1
                    if isinstance(data, dict):
                        priced = set()
                        for book in data.get("bookmakers") or []:
                            if not isinstance(book, dict):
                                continue
                            pairs = complete_market_pairs(book, wanted)
                            name = str(book.get("title") or book.get("key") or book.get("name") or "unknown")[:90]
                            for market_key, choices in pairs.items():
                                metric = METRIC[market_key]
                                if metric not in priced:
                                    priced.add(metric)
                                    report["priced"][metric] += 1
                                by_book = report["bookmakers"][metric]
                                by_book[name] = by_book.get(name, 0) + 1
                                if len(report["samples"][metric]) < 8:
                                    report["samples"][metric].append({
                                        "provider_event_id": eid, "bookmaker": name,
                                        **choices[0],
                                    })
                        record["priced"] = sorted(priced)
        except (RuntimeError, ValueError) as exc:
            report["errors"] += 1
            record["error"] = str(exc)
            if "reserve" in str(exc).lower() or "cap" in str(exc).lower():
                report["stopped"] = str(exc)
        report["per_event"].append(record)
        if report["stopped"]:
            break
    report["api_calls"] = client.calls
    report["provider_remaining"] = client.remaining
    report["events_not_queried"] = max(0, len(eligible) - report["events_queried"])
    report["matched_vs_unmatched"] = {
        "matched_blinq": sum(r["matched_blinq"] for r in report["per_event"]),
        "not_matched_blinq": sum(not r["matched_blinq"] for r in report["per_event"]),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    args = parser.parse_args()
    if not 1 <= args.max_calls <= MAX_CALLS:
        parser.error("max-calls must be 1..400")
    key = os.getenv("PROPL", "").strip()
    if not key:
        raise RuntimeError("Existing PROPL GitHub secret is missing")
    repository = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
    folder = Path(".cache/tbt/propline_full_board_audit")
    store = ReleaseStore(repository, "tbt-predictions-v1", folder)
    store.download(extra_names=("feed.json",), required_names=("feed.json",))
    feed = json.loads((folder / "feed.json").read_text(encoding="utf-8"))
    if not isinstance(feed, dict) or not isinstance(feed.get("upcoming"), list):
        raise ValueError("Invalid current serving feed")
    client = PropLineClient(key, max_calls=args.max_calls, min_remaining=DAILY_RESERVE)
    report = scan_board(client, now=datetime.now(timezone.utc),
                        known_predictions=feed["upcoming"])
    report["feed_generated_at"] = feed.get("generated_at")
    report["published_fixture_count"] = len(feed["upcoming"])
    output = Path("reports/propline_full_board_audit.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "per_event"}
    print(json.dumps({"propline_full_board_audit": summary}, ensure_ascii=False), flush=True)
    print(f"Artifact: {output}", flush=True)


if __name__ == "__main__":
    main()
