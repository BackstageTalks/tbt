#!/usr/bin/env python3
"""Read-only, <=5 request API Pro ACE quote check for already-issued player picks.

No CDB, model, website or Telegram writes. Uses RapidTennisClient, which
requires the existing durable shared-budget reservation before a provider call.
Reports individual player O/U offers, even when only one side is priced.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.projection_odds import _normal, _explicit_line, _over_under
from tbt.services.market_selection import _walk_market_rows, _outcome_text, _price

TARGETS = ("fritz", "medvedev", "zverev")
OUTPUT = Path("api_pro_aces_targeted_report.json")
INPUT = Path("daily_offer_snapshot.json")


def event_targets(snapshot: dict) -> list[dict]:
    found = []
    for row in snapshot.get("ace_picks", []):
        if not isinstance(row, dict) or str(row.get("market") or "").lower() != "aces":
            continue
        eid = str(row.get("event_id") or "").strip()
        if not eid:
            continue
        players = [p for p in (row.get("player1"), row.get("player2")) if isinstance(p, dict)]
        wanted = str(row.get("selection_id") or "").strip()
        selected = next((p for p in players if str(p.get("id") or "") == wanted), None)
        if not selected:
            continue
        name = str(selected.get("name") or "").strip()
        if not name:
            continue
        found.append({
            "event_id": eid,
            "player": name,
            "player_slot": 1 if players and selected is players[0] else 2,
            "projection": row.get("projection"),
            "scheduled_at": row.get("scheduled_at"),
            "priority": 0 if any(t in _normal(name).split() for t in TARGETS) else 1,
        })
    found.sort(key=lambda r: (r["priority"], str(r["scheduled_at"] or ""), r["event_id"]))
    unique = {}
    for row in found:
        unique.setdefault((row["event_id"], _normal(row["player"])), row)
    return list(unique.values())


def scan(payload, pick: dict) -> dict:
    player = _normal(pick["player"])
    slot = pick["player_slot"]
    ace_markets, selections = [], []
    for raw, market in _walk_market_rows(payload):
        name = _normal(market)
        if "ace" not in name:
            continue
        outcome = _outcome_text(raw)
        side = _over_under(outcome, raw)
        price = _price(raw)
        line = _explicit_line(raw, outcome)
        pfield = _normal(raw.get("playerName") or raw.get("player_name")
                         or raw.get("participantName") or raw.get("participant_name"))
        mentioned = player in name or pfield == player or (
            f"player {slot}" in name or f"player{slot}" in name
        )
        entry = {"market": str(market)[:110], "outcome": str(outcome)[:80],
                 "player_field": pfield[:80], "line": line,
                 "price": price, "side": side, "matches_player": mentioned}
        if len(ace_markets) < 20:
            ace_markets.append(entry)
        not_full_match = any(token in name for token in (
            "most", "winner", "who", "more than", "set 1", "1st set",
            "first set", "set 2", "second set", "tiebreak", "tie break"
        ))
        if not mentioned or not side or price is None or line is None or not (0.5 <= line <= 40.5) or not_full_match:
            continue
        selections.append({"player":pick["player"],"event_id":pick["event_id"],
                           "side":side,"line":line,"odds":price,"market":str(market)[:110]})
    return {"ace_market_samples": ace_markets, "individual_bookmaker_selections": selections}


def main() -> int:
    source = json.loads(INPUT.read_text(encoding="utf-8"))
    picks = event_targets(source)
    output = {
        "schema": 1, "mode": "api_pro_targeted_read_only",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_day": source.get("betting_day"),
        "snapshot_confirmed": source.get("confirmed_only"),
        "ace_picks_in_snapshot": sum(r.get("market") == "aces" for r in source.get("ace_picks", []) if isinstance(r, dict)),
        "eligible_targeted_picks": len(picks), "max_paid_requests": 5,
        "events": [], "requests_used": 0, "verified_player_ace_selections": 0,
        "production_writes": 0, "published_picks_changed": 0
    }
    if source.get("confirmed_only") is not True:
        output["error"] = "snapshot_not_confirmed"
    else:
        client = None
        try:
            client = RapidTennisClient()
            client.request_limit = min(client.request_limit or 5, 5)
            client.retry_attempts = 1
            for pick in picks[:5]:
                record = {**pick}
                try:
                    payload = client.event_odds(pick["event_id"], provider_id=1)
                    record.update(scan(payload,pick))
                except Exception as exc:
                    record["error"] = type(exc).__name__ + ": " + str(exc)[:250]
                output["events"].append(record)
                if client.rate_limit_remaining is not None and client.rate_limit_remaining <= 500:
                    output["quota_guard_stop"] = True
                    break
            output["requests_used"] = client.request_count
            output["verified_player_ace_selections"] = sum(
                len(r.get("individual_bookmaker_selections", [])) for r in output["events"]
            )
        except Exception as exc:
            output["error"] = type(exc).__name__ + ": " + str(exc)[:250]
        finally:
            if client:
                client.close()
    OUTPUT.write_text(json.dumps(output,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    print("API_PRO_ACES_TARGETED " + json.dumps(output,ensure_ascii=False,allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
