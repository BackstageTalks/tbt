"""One-off, zero-CDB-write comparison of today's confirmed ACE offers and free PropLine odds.

Only reads the signed tbt-data release, production serving canary and the pre-match
PropLine free API. No publishing, model changes, or historical price backfill.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram_offer_publisher as tg
import telegram_more_aces as more
from tbt.services.feed import main_tour_aces
from tbt.services.issued_authority import row_authority_key
from tbt.services.propline_live import (
    PropLineClient, _events, _markets, _match_board_with_diagnostics,
    _name, _price,
)

SOURCE = Path("/tmp/today-aces-free-probe/daily_offer_snapshot.json")
DFS = {"dabble", "sleeper", "prizepicks", "underdog", "parlayplay", "draftkings_pick6"}
BOOKS = {"napoleon", "superbet_pl", "superbet_ro"}
MOST_TOKENS = ("most", "more", "higher", "winner", "superiority", "who")
LOCAL_DAY = "2026-11-17"


def eligible(row, now, site_keys):
    if not isinstance(row, dict) or row.get("market") not in ("aces", "most_aces"):
        return False
    if not main_tour_aces(row):
        return False
    try:
        when = tg.stamp(row["scheduled_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (when > now and tg.day(when) == LOCAL_DAY
            and when.astimezone(tg.TZ).date().isoformat() == LOCAL_DAY
            and row_authority_key(row, "ace_picks") in site_keys)


def player(row):
    sid = str(row.get("selection_id") or "")
    return next((str(p["name"]) for p in (row["player1"], row["player2"])
                 if str(p.get("id")) == sid), None)


def price(raw):
    value = _price(raw)
    return round(value, 3) if value is not None and math.isfinite(value) else None


def exact_over(row, book):
    """Observe two independently distinct contract shapes; never merge books."""
    chosen = player(row)
    if row.get("price_contract") != "player_total_ou" or not chosen:
        return [], []
    direction = str(row.get("ou_side") or "").lower()
    try:
        line = float(row["market_line"])
    except (ValueError, TypeError):
        return [], []
    if direction not in ("over", "under") or line < 0 or not math.isfinite(line):
        return [], []
    full_ou, milestone = [], []
    for market in book.get("markets") or []:
        if market.get("key") != "player_aces":
            continue
        groups = defaultdict(dict)
        for o in market.get("outcomes") or []:
            if not isinstance(o, dict) or _name(o.get("description")) != _name(chosen):
                continue
            val = price(o.get("price"))
            if val is None:
                continue
            side = _name(o.get("name"))
            point = o.get("point")
            if side in ("over", "under") and point is not None:
                try:
                    point = float(point)
                except (TypeError, ValueError):
                    continue
                if point == line and side not in groups[point]:
                    groups[point][side] = val
            if (direction == "over" and float(line).is_integer() is False
                    and abs(line % 1 - 0.5) < 1e-9):
                match = re.fullmatch(r"\s*(\d+)\s*\+\s*aces\s*", str(o.get("name") or ""), re.I)
                if match and int(match.group(1)) == line + 0.5:
                    milestone.append({
                        "bookmaker": str(book.get("key") or ""), "price": val,
                        "market": str(o.get("name")), "equivalent_line": line,
                        "bookmaker_last_update": market.get("last_update"),
                        "contract_status": "over_equivalent_requires_settlement_validation",
                    })
        for found_line, sides in groups.items():
            if set(sides) == {"over", "under"}:
                full_ou.append({
                    "bookmaker": str(book.get("key") or ""),
                    "line": found_line,
                    "over": sides["over"], "under": sides["under"],
                    "selected_side": direction,
                    "bookmaker_last_update": market.get("last_update"),
                })
    return full_ou, milestone


def most_key(key):
    k = str(key or "").lower()
    return "ace" in k and any(t in k for t in MOST_TOKENS) and not any(
        x in k for x in ("total", "set", "period", "handicap", "over", "under"))


def main():
    now = datetime.now(timezone.utc)
    snap = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert snap.get("confirmed_only") is True and snap.get("betting_day") == LOCAL_DAY == tg.day(now), "wrong bet day"
    site = more.site_readback("https://agreeable-sky-011a7fe10.7.azurestaticapps.net")
    assert (site.get("ready") is True and site.get("stale") is False and site.get("betting_day") == LOCAL_DAY
            and site.get("generated_at") == snap.get("source_feed_generated_at")), "signed offer differs from live web"
    site_keys = set(((site.get("offer_authority_keys") or {}).get("aces")) or [])
    rows = [r for r in (snap.get("ace_picks") or []) if eligible(r, now, site_keys)]
    aces = [r for r in rows if r["market"] == "aces"]
    most = [r for r in rows if r["market"] == "most_aces"]
    fixtures = {}
    for row in rows:
        event = str(row["event_id"])
        same = fixtures.get(event)
        if same:
            if (same.get("player1") != row.get("player1") or
                    same.get("player2") != row.get("player2") or
                    same.get("scheduled_at") != row.get("scheduled_at")):
                raise ValueError("Conflicting same-event identity in published offer")
        else:
            fixtures[event] = row
    # One bulk API request plus event-market lookups, all within provider reserve.
    client = PropLineClient(os.environ["PROPL"], max_calls=32, min_remaining=170)
    bulk = client.get("/sports/tennis/odds", {"markets": "player_aces,total_aces"})
    board = _events(bulk)
    linked, diag = _match_board_with_diagnostics(list(fixtures.values()), board, now)
    by_id = {str(r["event_id"]): p for r, p in linked}
    by_propline_id = {str(p["id"]): p for r,p in linked}
    report = {
        "betting_day": LOCAL_DAY,
        "captured_at": now.isoformat(),
        "source_verified_web_generation": site["generated_at"],
        "offered_future_aces_ou": len(aces),
        "offered_future_most_aces": len(most),
        "future_unique_fixture_count": len(fixtures),
        "available_bulk_provider_events": len(board),
        "fixture_match": diag,
        "matched_unique_events": len(linked),
        "provider_ace_market_count": sum(
            1 for p in board for b in p.get("bookmakers") or []
            for m in b.get("markets") or [] if m.get("key") == "player_aces"
        ),
        "aces_rows": [],
        "most_summary": {},
        "most_rows": [],
        "provider_requests": 0,
        "provider_remaining": None,
        "cdb_writes": 0,
        "published_picks_changed": 0,
        "paid_provider_calls": 0,
    }

    for row in aces:
        event = str(row["event_id"])
        item = {"match": [row["player1"]["name"], row["player2"]["name"]],
                "selected_player": player(row), "scheduled_at": row["scheduled_at"],
                "side": row.get("ou_side"), "line": row.get("market_line"),
                "provider_event_id": None,
                "sportsbook_full_ou": [], "sportsbook_exact_over_milestones": [],
                "dfs_exact_ou": [], "match_status": "not_in_bulk_board"}
        if event in by_id:
            p = by_id[event]
            item["provider_event_id"] = p["id"]
            item["match_status"] = "matched"
            for book in p.get("bookmakers") or []:
                key = str(book.get("key") or "")
                complete, milestone = exact_over(row, book)
                if key in DFS:
                    item["dfs_exact_ou"].extend(complete)
                elif key in BOOKS:
                    item["sportsbook_full_ou"].extend(complete)
                    item["sportsbook_exact_over_milestones"].extend(milestone)
                else:
                    # Unclassified books need independent sportsbook verification.
                    if complete or milestone:
                        item.setdefault("unclassified_contracts", []).append(
                            {"book": key, "complete_ou": len(complete), "milestones": len(milestone)})
        report["aces_rows"].append(item)

    # Market-key discovery for exact VIAC ES contracts on all *matched* today's
    # offerings only. No API Pro calls; no in-play or unpriced assumptions.
    most_matched = {str(row["event_id"]): row for row in most if str(row["event_id"]) in by_id}
    found_keys = 0
    full_prices = 0
    checked = 0
    errors = 0
    limit_exceeded = 0
    for event_id, row in most_matched.items():
        if client.calls >= client.max_calls or (
                client.remaining is not None and client.remaining <= 175):
            limit_exceeded += 1
            continue
        provider_id = str(by_id[event_id]["id"])
        item = {"match": [row["player1"]["name"], row["player2"]["name"]],
                "selected_player": player(row), "provider_event_id": provider_id}
        report["most_rows"].append(item)
        try:
            keys = _markets(client.get(f"/sports/tennis/events/{provider_id}/markets"))
            checked += 1
            interesting = sorted(k for k in keys if most_key(k))
            item["exact_most_aces_market_keys"] = interesting
            if interesting:
                found_keys += 1
                # A single book/contract with precisely two participants and
                # valid prices; three-way/draw outcomes are separate contracts.
                valid = []
                if client.calls < client.max_calls and client.remaining > 175:
                    response = client.get(f"/sports/tennis/events/{provider_id}/odds",
                                          {"markets": ",".join(interesting)})
                    for book in response.get("bookmakers") or []:
                        for m in book.get("markets") or []:
                            if m.get("key") not in interesting:
                                continue
                            outs = m.get("outcomes") or []
                            names = {_name(o.get("name")) for o in outs if isinstance(o,dict)}
                            if len(outs) != 2 or names != {
                                _name(row["player1"]["name"]), _name(row["player2"]["name"])}:
                                continue
                            if not all(price(o.get("price")) for o in outs):
                                continue
                            valid.append({"bookmaker": book.get("key"), "market": m.get("key"),
                                          "prices": {o["name"]: price(o["price"]) for o in outs}})
                item["verified_two_way"] = valid
                full_prices += len(valid)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            item["error"] = type(exc).__name__
            errors += 1
    report["most_summary"] = {
        "offered_future": len(most),
        "matched_bulk_events": len(most_matched),
        "event_market_lists_checked": checked,
        "events_with_most_aces_key": found_keys,
        "bookmaker_two_way_prices": full_prices,
        "provider_errors": errors,
        "not_checked_due_quota_or_run_cap": limit_exceeded,
    }
    report["provider_requests"] = client.calls
    report["provider_remaining"] = client.remaining
    out = Path("/tmp/blinq-today-free-aces-quote-report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n",
                   encoding="utf-8")
    print("TODAY_FREE_QUOTE_RESULT=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    assert report["cdb_writes"] == report["published_picks_changed"] == report["paid_provider_calls"] == 0


if __name__ == "__main__":
    main()
