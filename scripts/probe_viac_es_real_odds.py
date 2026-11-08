"""Bounded, read-only provider quote audit for ball-marked VIAC ES.

Only exact 'which player serves more aces' markets. O/U, match-winner,
synthetic price, stale fixtures, and 3-way draw markets are not substitutes.
This probe does not publish Telegram prices or write canonical CDB.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.market_selection import _walk_market_rows, _outcome_text, _price, _match_side
from tbt.services.projection_odds import extract_player_superiority_odds
from tbt.services.propline_live import PropLineClient, _events, _match_board_with_diagnostics, _markets, _price as prop_price
import telegram_offer_publisher as tg
import telegram_more_aces as more


def _market_key(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def exact_aces_quote(payload, p1, p2):
    """Reject quote mixing, extra Tie/Draw selection, and player-total O/U."""
    groups = {}
    for outcome, market in _walk_market_rows(payload):
        norm = _market_key(market)
        if ("ace" not in norm or not any(x in norm for x in
                ("most", "winner", "more", "higher", "who", "superiority"))):
            continue
        if any(x in norm for x in ("total", "over", "under", "handicap", "set", "period", "tie break")):
            continue
        groups.setdefault(market, []).append(outcome)

    valid = []
    invalid = Counter()
    for market, outcomes in groups.items():
        prices = {}
        extra = False
        for row in outcomes:
            # A market with a third Tie/Draw selection is a distinct contract.
            label = _outcome_text(row)
            side = _match_side(label, p1, p2)
            price = _price(row)
            if side not in (1, 2) or price is None or price <= 1:
                extra = True
                break
            if side in prices:  # ambiguity, even if same decimal
                extra = True
                break
            prices[side] = round(float(price), 3)
        if extra:
            invalid["extra_draw_unknown_or_duplicate"] += 1
            continue
        if set(prices) != {1, 2}:
            invalid["missing_complete_pair"] += 1
            continue
        witness = extract_player_superiority_odds({"markets": [
            {"marketName": market, "choiceName": p1, "decimalOdds": prices[1]},
            {"marketName": market, "choiceName": p2, "decimalOdds": prices[2]},
        ]}, "aces", p1, p2)
        if not witness or witness["player1_odds"] != prices[1] or witness["player2_odds"] != prices[2]:
            invalid["native_parser_disagrees"] += 1
            continue
        valid.append({"market_name": market, "player1_odds": prices[1],
                      "player2_odds": prices[2], "settlement": "two_way_only"})
    # Never choose an arbitrary market if two distinct valid quotes compete.
    if len(valid) != 1:
        return None, {"observed_candidate_markets": len(groups),
                      "validated_two_way_markets": len(valid),
                      "rejected": dict(invalid)}
    return valid[0], {"observed_candidate_markets": len(groups),
                      "validated_two_way_markets": 1,
                      "rejected": dict(invalid)}


def prop_aces_quote(payload, names, desired_key):
    """Build one book's exact market without synthetic O/U conversion."""
    matches = []
    for book in payload.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        name = str(book.get("title") or book.get("key") or book.get("name") or "").strip()
        for market in book.get("markets") or []:
            if not isinstance(market, dict) or str(market.get("key") or "") != desired_key:
                continue
            converted = []
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, dict):
                    continue
                price = prop_price(outcome.get("price"))
                # Invalid/extra prices remain visible and thus reject the whole market.
                converted.append({"marketName": desired_key, "choiceName": outcome.get("name"),
                                  "decimalOdds": price or 0})
            quote, evidence = exact_aces_quote({"markets": converted}, *names)
            if quote:
                matches.append({**quote, "bookmaker": name})
    if len(matches) != 1:
        return None
    return matches[0]


def select_current(snapshot, site, now, limit):
    selected = more.offered_rows(snapshot, now)
    more.verify_same_website(snapshot, site, selected, now)
    by_event = {}
    for row in snapshot["ace_picks"]:
        ball = more.ball_player(row)
        if ball:
            by_event[(str(row["event_id"]), str(ball["id"]))] = row
    fixtures = []
    for selected_row in selected:
        identity = (selected_row["event_id"], selected_row["selection_id"])
        row = by_event.get(identity)
        if not row:
            raise ValueError("Website ball row disappeared from confirmed snapshot")
        fixtures.append(row)
    fixtures.sort(key=lambda r: (str(r.get("scheduled_at") or ""), str(r.get("event_id") or "")))
    return fixtures[:limit], len(fixtures)


def audit(snapshot, site, now, *, rapid, prop, max_events=3):
    matches, total = select_current(snapshot, site, now, max_events)
    result = {"schema": 1, "mode": "readonly_exact_most_aces", "betting_day": tg.day(now),
              "generated_at": now.isoformat(), "source_snapshot_generated_at": snapshot.get("generated_at"),
              "candidate_ball_marked": total, "events_probed": len(matches),
              "max_events": max_events, "cdb_writes": 0, "tg_messages_sent": 0,
              "rows": [], "provider_requests": {"api_pro": 0, "propline": 0}}
    if not matches:
        result["status"] = "no_future_ball_marked_fixtures"
        return result
    rapid.request_limit = max_events
    rapid.retry_attempts = 1
    unresolved = []
    for row in matches:
        p1, p2 = row["player1"]["name"], row["player2"]["name"]
        selected = more.ball_player(row)
        record = {"event_id": str(row["event_id"]), "player1": p1, "player2": p2,
                  "ball_player": selected["name"], "ball_player_id": str(selected["id"]),
                  "scheduled_at": row["scheduled_at"], "provider": None, "quote": None}
        result["rows"].append(record)
        try:
            payload = rapid.event_odds(row["event_id"], provider_id=1)
            quote, diag = exact_aces_quote(payload, p1, p2)
            record["api_pro"] = diag
            if quote:
                side = 1 if str(selected["id"]) == str(row["player1"]["id"]) else 2
                record["quote"] = quote["player1_odds"] if side == 1 else quote["player2_odds"]
                record["provider"] = "tennisapi1"
                record["market_name"] = quote["market_name"]
                record["price_contract"] = "most_aces_two_way"
                record["quote_freshness"] = "observed_pre_match_no_provider_quote_clock"
                continue
        except Exception as exc:
            record["api_pro"] = {"error_class": exc.__class__.__name__}
        unresolved.append((row, record))

    result["provider_requests"]["api_pro"] = rapid.request_count
    result["rapidapi_header_remaining"] = rapid.rate_limit_remaining
    if unresolved and prop is not None:
        # PropLine has separate provider-day reserve and hard per-run cap.
        try:
            board = _events(prop.get("/sports/tennis/events"))
            linked, diagnostics = _match_board_with_diagnostics(
                [row for row, _ in unresolved], board, now)
            result["propline_match"] = diagnostics
            by_id = {str(row["event_id"]): (row, record) for row, record in unresolved}
            for row, event in linked:
                original, record = by_id[str(row["event_id"])]
                if prop.calls + 2 > prop.max_calls:
                    record["propline"] = "request_cap"
                    continue
                try:
                    keys = _markets(prop.get(f"/sports/tennis/events/{event['id']}/markets"))
                    candidates = sorted(key for key in keys if "ace" in _market_key(key)
                        and any(t in _market_key(key) for t in ("most", "winner", "more", "higher")))
                    record["propline_advertised"] = candidates[:12]
                    if not candidates:
                        record["propline"] = "no_advertised_most_aces_market"
                        continue
                    # Probe one exact market only; never infer from player_aces O/U.
                    chosen = candidates[0]
                    payload = prop.get(f"/sports/tennis/events/{event['id']}/odds",
                                       {"markets": chosen})
                    quote = prop_aces_quote(payload,
                                           (original["player1"]["name"], original["player2"]["name"]),
                                           chosen)
                    if quote:
                        selected = more.ball_player(original)
                        side = 1 if str(selected["id"]) == str(original["player1"]["id"]) else 2
                        record["quote"] = quote["player1_odds"] if side == 1 else quote["player2_odds"]
                        record["provider"] = "propline"
                        record["bookmaker"] = quote["bookmaker"]
                        record["market_name"] = chosen
                        record["price_contract"] = "most_aces_two_way"
                        record["quote_freshness"] = "observed_pre_match_no_provider_quote_clock"
                    else:
                        record["propline"] = "market_unpriced_or_not_exact_two_way"
                except Exception as exc:
                    record["propline"] = {"error_class": exc.__class__.__name__}
        except Exception as exc:
            result["propline_error"] = exc.__class__.__name__
        result["provider_requests"]["propline"] = prop.calls
        result["propline_header_remaining"] = prop.remaining
    result["priced_exact"] = sum(row["quote"] is not None for row in result["rows"])
    result["unpriced"] = len(result["rows"]) - result["priced_exact"]
    result["status"] = "audited"
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=".cache/tbt/viac-es-odds/probe.json")
    p.add_argument("--max-events", type=int, default=3)
    args = p.parse_args()
    if not 1 <= args.max_events <= 3:
        raise ValueError("A safety cap of three fixtures is mandatory")
    now = datetime.now(timezone.utc)
    snap = tg.snapshot(Path("/tmp/blinq-most-aces-probe/assets"))
    site = more.site_readback(os.getenv("BLINQ_PRODUCTION_URL",
            "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"))
    rapid = RapidTennisClient()
    propkey = os.getenv("PROPL", "")
    prop = PropLineClient(propkey, max_calls=7) if propkey else None
    report = audit(snap, site, now, rapid=rapid, prop=prop, max_events=args.max_events)
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                    encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("status", "candidate_ball_marked",
          "events_probed", "priced_exact", "unpriced", "provider_requests", "cdb_writes")},
          ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
