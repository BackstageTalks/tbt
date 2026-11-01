#!/usr/bin/env python3
"""Read-only PropLine ACES discovery. No CDB/feed writes, no pick filtering.

One sport-wide request first; optional per-event fallback is quota guarded.
Prints exact real-bookmaker O/U lines with sources, never synthetic DFS payouts.
"""
# UTC quota-reset single-run check 2026-11-01: research-only, do not alter production picks.
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.services.propline_live import PropLineClient, _price, _name, MIN_PROVIDER_REMAINING

DFS_KEYS = {"prizepicks", "prize picks", "underdog", "underdog fantasy",
            "draftkings pick6", "pick6", "sleeper", "dabble", "parlayplay"}
ACESTYPES = {"player_aces"}  # Don't mistake generic match-total aces for player props.


def is_dfs(book):
    key = _name(book.get("key"))
    title = _name(book.get("title") or book.get("name"))
    return any(key == token or key.startswith(token + " ") or
               title == token or title.startswith(token + " ") for token in DFS_KEYS)


def events(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("bookmakers"), list):
            return [payload]
        for key in ("events", "data", "results"):
            if isinstance(payload.get(key), list):
                return events(payload[key])
    return []


def extract_quotes(payload):
    """No cross-book joins, only full-match same-book same-player same-line pairs."""
    real = []
    rejected = Counter()
    raw_book_names = Counter()
    listed = events(payload)
    for event in listed:
        event_id = str(event.get("id") or event.get("event_id") or "")
        when = str(event.get("commence_time") or "")
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            book_name = str(book.get("title") or book.get("key") or "Unknown")
            raw_book_names[book_name] += 1
            dfs = is_dfs(book)
            for market in book.get("markets") or []:
                if not isinstance(market, dict) or market.get("key") not in ACESTYPES:
                    continue
                if market.get("period") not in (None, "", "full", "match"):
                    rejected["partial_period"] += 1
                    continue
                candidates = {}
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, dict):
                        continue
                    side = _name(outcome.get("name"))
                    if side not in ("over", "under"):
                        continue
                    player = str(outcome.get("description") or outcome.get("player_name") or "").strip()
                    if not player:
                        rejected["no_player_identity"] += 1
                        continue
                    point = outcome.get("point")
                    try:
                        line = float(point)
                    except (ValueError, TypeError):
                        rejected["missing_line"] += 1
                        continue
                    if not math.isfinite(line) or not .5 <= line <= 40.5:
                        rejected["invalid_line"] += 1
                        continue
                    odds = _price(outcome.get("price"))
                    if odds is None:
                        rejected["missing_price"] += 1
                        continue
                    # Keyed to SAME market row, player and exact line; never
                    # mix odds from another bookmaker or player.
                    key = (_name(player), line)
                    candidates.setdefault(key, {"player": player, "line": line})[side] = odds
                for item in candidates.values():
                    if "under" not in item or "over" not in item:
                        rejected["one_sided"] += 1
                        continue
                    if dfs:
                        rejected["fantasy_pairs"] += 1
                        continue
                    real.append({
                        "event_id": event_id,
                        "match": str(event.get("home_team") or "") + " vs " + str(event.get("away_team") or ""),
                        "commence_time": when,
                        "tier": event.get("tier"),
                        "bookmaker": book_name,
                        "bookmaker_key": book.get("key"),
                        "market": market.get("key"),
                        "market_period": market.get("period"),
                        "line_type": market.get("line_type"),
                        "last_update": market.get("last_update"),
                        **item,
                    })
    return {
        "events_in_payload": len(listed),
        "books_seen": dict(raw_book_names.most_common(30)),
        "real_pairs": real,
        "rejected": dict(rejected),
    }


def self_test():
    fixture = [
        {"id": "test-1", "home_team": "A", "away_team": "B", "bookmakers": [
            {"key": "prizepicks", "title": "PrizePicks", "markets": [
                {"key": "player_aces", "outcomes": [
                    {"name": "Over", "description": "A", "point": 10.5, "price": 100},
                    {"name": "Under", "description": "A", "point": 10.5, "price": 100},
                ]}]},
            {"key": "draftkings", "title": "DraftKings", "markets": [
                {"key": "player_aces", "line_type": "main", "outcomes": [
                    {"name": "Over", "description": "A", "point": 12.5, "price": 132},
                    {"name": "Under", "description": "A", "point": 12.5, "price": -160},
                ]},
                {"key": "player_aces", "line_type": "alternate", "outcomes": [
                    {"name": "Over", "description": "A", "point": 13.5, "price": 175},
                    {"name": "Under", "description": "A", "point": 13.5, "price": -225},
                ]},
                {"key": "player_aces", "period": "s1", "outcomes": [
                    {"name": "Over", "description": "A", "point": 3.5, "price": -110},
                    {"name": "Under", "description": "A", "point": 3.5, "price": -110},
                ]},
            ]},
        ]},
    ]
    out = extract_quotes(fixture)
    assert len(out["real_pairs"]) == 2, out
    assert [x["line"] for x in out["real_pairs"]] == [12.5, 13.5]
    assert out["real_pairs"][0]["under"] == 1.625
    assert out["rejected"]["fantasy_pairs"] == 1
    assert out["rejected"]["partial_period"] == 1
    assert extract_quotes([{"id": "2", "bookmakers": [
        {"key": "draftkings", "markets": [{"key": "player_aces", "outcomes": [
            {"name": "Over", "description": "A", "point": 7.5, "price": -110}]}]},
        {"key": "bovada", "markets": [{"key": "player_aces", "outcomes": [
            {"name": "Under", "description": "A", "point": 7.5, "price": -110}]}]},
    ]}])["real_pairs"] == []
    print("SELF_TEST: PASS; separate fantasy / real lines / periods / bookmakers")


def run_live(max_calls, max_event_fallback):
    # No writes. Shared PropLine API key, enforced provider header reserve.
    secret = os.environ.get("PROPL", "")
    if not secret:
        print("LIVE_PROBE: NO_SECRET; no requests attempted")
        return 3
    client = PropLineClient(secret, max_calls=max_calls,
                            min_remaining=MIN_PROVIDER_REMAINING)
    checked = []
    try:
        bulk = client.get("/sports/tennis/odds", {"markets": "player_aces"})
        first = extract_quotes(bulk)
        checked.append({"source": "bulk", **first})
        if not first["real_pairs"] and max_event_fallback:
            board = client.get("/sports/tennis/events")
            now = datetime.now(timezone.utc)
            upcoming = []
            for row in events(board):
                try:
                    dt = datetime.fromisoformat(str(row.get("commence_time")).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > now and row.get("id") and row.get("doubles") is not True:
                    upcoming.append((dt, row))
            upcoming.sort(key=lambda x: x[0])
            for _, row in upcoming[:min(max_event_fallback, max(0, max_calls-client.calls))]:
                eid = str(row["id"])
                data = client.get(f"/sports/tennis/events/{eid}/odds",
                                  {"markets": "player_aces"})
                parsed = extract_quotes(data)
                checked.append({"source": "event", "id": eid, **parsed})
    except RuntimeError as exc:
        print("LIVE_PROBE_ERROR:", str(exc))
    unique = {}
    failures = Counter()
    for item in checked:
        failures.update(item["rejected"])
        for q in item["real_pairs"]:
            identity = (q["event_id"], q["bookmaker_key"], q["player"], q["line"])
            unique[identity] = q
    report = {
        "schema": 1, "mode": "read_only_aces_real_quote_probe",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider_calls": client.calls, "call_limit": max_calls,
        "provider_remaining_header": client.remaining,
        "events_checked": sum(item["events_in_payload"] for item in checked),
        "real_two_sided_pairs": len(unique),
        "real_books": dict(Counter(q["bookmaker"] for q in unique.values())),
        "rejected": dict(failures),
        "samples": sorted(unique.values(), key=lambda q: (
            0 if q.get("tier") in ("atp", "wta") else 1,
            q["commence_time"], q["event_id"], q["bookmaker"], q["line"]
        ))[:30],
        "writes_to_cdb_or_feed": 0, "published_picks_changed": 0,
    }
    print("PROPLINE_ACES_PROBE " + json.dumps(report, ensure_ascii=False))
    Path("propline_aces_live_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if checked else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--max-calls", type=int, default=12)
    ap.add_argument("--event-fallback", type=int, default=8)
    args = ap.parse_args()
    if args.self_test:
        self_test()
    if args.live:
        if args.max_calls < 1 or args.max_calls > 50:
            ap.error("--max-calls must be 1-50")
        return run_live(args.max_calls, args.event_fallback)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
