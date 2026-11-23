"""Offline candidate: Prop-Line owns contracts; the count model scores them.

No provider requests, publication, training or mutation of champion cards.
Archive validation and exact two-player fixture matching are shared with the
existing morning archive reader. Local statistical prices remain first-class.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import timezone
import math

from ace_working_odds import working_ace_odds, PRICE_BASIS
from propline_evening_quotes import validated_events, _event_identity, _same_person, FANTASY
from tbt.services.projection_odds import extract_player_total_ou, _player_ou_probability


def project_candidates(history, predictions, *, now):
    """Reuse the serving count estimator, without Most-Aces gap/shortlist bias."""
    from tbt.services.ace_selection import _history_index, _projection, ace_eligibility_reason
    from propline_evening_quotes import _stamp

    if now.tzinfo is None:
        raise ValueError("Timezone-aware observation clock required")
    now = now.astimezone(timezone.utc)
    histories, baselines, _ = _history_index(history, now.replace(hour=0, minute=0, second=0, microsecond=0))
    cards = []
    for row in predictions:
        start = _stamp(row.get("scheduled_at"))
        if not start or start <= now or ace_eligibility_reason(row) != "eligible":
            continue
        p1, p2 = row.get("player1") or {}, row.get("player2") or {}
        if not p1.get("id") or not p2.get("id") or p1["id"] == p2["id"]:
            continue
        try:
            best_of = int(row["best_of"]) if row.get("best_of") is not None else None
        except (TypeError, ValueError):
            best_of = None
        values = [_projection(str(a["id"]), str(b["id"]), "aces", histories,
                   baselines["aces"], now, surface=str(row.get("surface") or "unknown").lower(),
                   best_of=best_of) for a, b in ((p1, p2), (p2, p1))]
        card = deepcopy(row)
        for field in ("betting", "market_publication_candidates", "match_winner_market"):
            card.pop(field, None)
        card.update(market="aces", selection_id=str(p1["id"]),
                    projection=values[0]["estimate"] if values[0] else None,
                    opponent_projection=values[1]["estimate"] if values[1] else None,
                    projection_model="ace-count-projection-v4")
        cards.append(card)
    return cards


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def offered_contracts(event, player):
    """Only full-match sportsbook contracts; DFS multipliers are not odds."""
    for market in event.get("aces_markets", []):
        kind = market.get("kind")
        if kind == "player_aces_ou":
            for pair in market.get("verified_pairs", []):
                if _same_person(pair.get("player"), player):
                    for side in ("over", "under"):
                        yield {"line": pair["line"], "side": side,
                               "odds": pair.get(side), "bookmaker": market["bookmaker"]}
        elif kind == "player_aces_milestone":
            for quote in market.get("verified_single_prices", []):
                if _same_person(quote.get("player"), player):
                    yield {"line": quote["equivalent_over_line"], "side": "over",
                           "odds": quote.get("odds"), "bookmaker": market["bookmaker"]}
    # A native offered line survives a missing price. This is the only path
    # to local pricing: never derive the boundary from the model. The archive
    # validator above has already checked this raw payload's identity/hash.
    for book in (event.get("provider_raw_event") or {}).get("bookmakers", []):
        bookmaker = str(book.get("key") or book.get("title") or "").strip()
        if not bookmaker or bookmaker.casefold() in FANTASY:
            continue
        for market in book.get("markets", []):
            if market.get("key") != "player_aces":
                continue
            for outcome in market.get("outcomes", []):
                side = str(outcome.get("name") or "").lower()
                if (side in ("over", "under") and outcome.get("price") is None
                        and _same_person(outcome.get("description"), player)):
                    yield {"line": outcome.get("point"), "side": side,
                           "odds": None, "bookmaker": bookmaker}


def choose_line(projection, offers):
    """Prefer OVER; otherwise UNDER. Closest offered cushion >=1.5 wins.

    Never fabricate a line to hit the cushion exactly. E.g. 10.5 -> UNDER
    12.5 when that is the available eligible contract. Deterministic ties.
    """
    mean = _number(projection)
    if mean is None or mean < 0:
        return None
    eligible = []
    for offer in offers:
        line = _number(offer.get("line"))
        side = offer.get("side")
        # Half-count contracts avoid an unmodelled integer push probability.
        if line is None or not 0.5 <= line <= 40.5 or line % 1 != 0.5:
            continue
        gap = mean - line if side == "over" else line - mean
        if side not in ("over", "under") or gap < 1.5 - 1e-9:
            continue
        eligible.append((side != "over", gap, str(offer.get("bookmaker", "")), offer))
    return min(eligible, key=lambda x: x[:3])[3] if eligible else None


def price_contract(row, slot, offer, rapid_payload):
    """Price only the exact chosen player/line/side: RapidAPI -> Prop -> local."""
    player = row[f"player{slot}"]
    exact = extract_player_total_ou(rapid_payload, "aces", player["name"],
                                    player_slot=slot, allow_one_sided=True)
    for option in exact:
        price = _number(option.get(offer["side"]))
        if option["line"] == offer["line"] and price is not None and 1 < price <= 100:
            return price, "rapidapi"
    price = _number(offer.get("odds"))
    if price is not None and 1 < price <= 100:
        return price, "propline"
    return working_ace_odds(row, selection_id=str(player["id"])), PRICE_BASIS


def select_candidate(cards, report, *, now, betting_day, rapid_payloads=None):
    """Score both player projections, at most one candidate tip per fixture.

    Missing offers are diagnostics, never tips. All other markets and the input
    list are preserved. A candidate with zero aces never empties TOP/Value.
    """
    events = validated_events(report, now=now, betting_day=betting_day)
    cards = list(cards)
    counts = Counter(str(c.get("event_id")) for c in cards if c.get("market") == "aces")
    links = {str(c.get("event_id")): [e for e in events if _event_identity(e, c) is not None]
             for c in cards if c.get("market") == "aces"}
    reverse = Counter(str(e["event_id"]) for linked in links.values() for e in linked)
    picks, diagnostics = [], []
    for row in cards:
        if row.get("market") != "aces":
            picks.append(deepcopy(row))
            continue
        event_id = str(row.get("event_id"))
        linked = links.get(event_id, [])
        if (counts[event_id] != 1 or len(linked) != 1
                or reverse[str(linked[0]["event_id"])] != 1):
            diagnostics.append({"event_id": event_id, "status": "bez ponuky",
                                "reason": "missing_or_ambiguous_fixture"})
            continue
        event = linked[0]
        candidates = []
        for slot in (1, 2):
            player = row[f"player{slot}"]
            selected = str(player["id"]) == str(row.get("selection_id"))
            mean = _number(row.get("projection" if selected else "opponent_projection"))
            offers = list(offered_contracts(event, player["name"]))
            chosen = choose_line(mean, offers)
            if chosen is None:
                continue
            price, source = price_contract(row, slot, chosen, (rapid_payloads or {}).get(event_id))
            if price is None:
                continue
            probability = _player_ou_probability(mean, "aces", chosen["line"])
            if chosen["side"] == "under":
                probability = 1 - probability
            candidate = deepcopy(row)
            candidate.update({
                "selection_id": str(player["id"]), "projection_subject": player["name"],
                "projection": mean, "opponent_projection": row.get("opponent_projection" if selected else "projection"),
                "market_line": chosen["line"], "ou_side": chosen["side"],
                "odds": price, "odds_source": source,
                "model_probability": round(probability, 4), "probability": round(probability, 4),
                "expected_value": round(probability * price - 1, 4),
                "price_contract": "player_total_ou", "line_source": "propline",
                "line_bookmaker": chosen["bookmaker"],
                "line_provider_event_id": event["event_id"], "captured_at": event["captured_at"],
                "line_evidence_sha256": event["source_sha256"],
                "selection_rule": "aces_line_first_candidate_v1", "candidate_only": True,
                "offer_status": "offered", "price_status": "candidate_only",
                "pick": f"{player['name']} {chosen['side'].title()} {chosen['line']:.1f} Aces",
            })
            candidate["selection"] = candidate["pick"]
            candidates.append(candidate)
        if candidates:
            picks.append(min(candidates, key=lambda c: (c["ou_side"] != "over",
                -c["model_probability"], c["selection_id"])))
        else:
            diagnostics.append({"event_id": event_id, "status": "bez ponuky",
                                "reason": "no_eligible_offered_line"})
    return {"schema": 1, "candidate_only": True, "picks": picks,
            "diagnostics": diagnostics, "incremental_provider_requests": 0}
