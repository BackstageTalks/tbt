"""Match-total shadow bets, derived solely from the issued board and point card."""
from collections import defaultdict
from datetime import datetime
import math
import os
from random import Random

LEVELS = ("ATP", "WTA", "Challenger", "WTA 125")


def enabled():
    return os.getenv("BLINQ_POINT_SG_SHADOW", "").lower() == "true"


def quote_lines(payload, market, bookmaker):
    # The request is scoped to a single book. Reject nested multi-book or
    # multi-clock feeds, and conflicting prices instead of pairing best prices.
    from .market_selection import _walk_market_rows, _outcome_text, _price
    from .projection_odds import _is_match_total_market, _explicit_line, _over_under

    tags = defaultdict(set)
    aliases = {"bookmaker": "book", "bookmakerName": "book", "bookmaker_name": "book",
               "bookmakerId": "book_id", "bookmaker_id": "book_id",
               "captured_at": "captured", "capturedAt": "captured",
               "updatedAt": "updated", "updated_at": "updated"}
    def provenance(node):
        if isinstance(node, list):
            for child in node:
                provenance(child)
        if isinstance(node, dict):
            for key, value in node.items():
                if key in aliases:
                    tags[aliases[key]].add(str(value))
                if isinstance(value, (dict, list)):
                    provenance(value)
    provenance(payload)
    if any(len(v) > 1 for v in tags.values()):
        return {}
    if tags["book"] and bookmaker not in tags["book"] and bookmaker != "TennisAPI:1":
        return {}
    pairs = defaultdict(lambda: defaultdict(set))
    for row, name in _walk_market_rows(payload):
        if not _is_match_total_market(name, market):
            continue
        label = _outcome_text(row)
        line, side, price = _explicit_line(row, label), _over_under(label, row), _price(row)
        if (line is None or line <= 0 or line * 2 != int(line * 2)
                or not side or price is None or not math.isfinite(price) or price <= 1):
            continue
        if (market == "games" and 8 <= line <= 80) or (market == "sets" and 1.5 <= line <= 5.5):
            pairs[line][side].add(price)
    return {line: {s: next(iter(v[s])) for s in ("over","under")} for line,v in pairs.items()
            if all(len(v[s]) == 1 for s in ("over","under"))}


def freeze(card, row, primary, alternatives, floor, frozen):
    market = row.get("market")
    if (market not in ("games","sets") or card["competition"] not in LEVELS
            or row.get("price_status") != "priced_projection" or not row.get("odds")
            or str(row.get("event_id")) != card["event_id"]
            or [str((row.get(k) or {}).get("id")) for k in ("player1","player2")] != card["players"]):
        return None
    start = datetime.fromisoformat(card["scheduled_at"])
    quoted = datetime.fromisoformat(row["captured_at"])
    if not quoted <= frozen < start or datetime.fromisoformat(row["scheduled_at"]) != start:
        return None
    source = row.get("odds_source")
    if source == "rapidapi" and row.get("provider_id") == 1:
        book, payload = "TennisAPI:1", primary
    elif source == "propline" and row.get("provider_id") == 2:
        book = row.get("odds_bookmaker")
        if not book or alternatives.get("bookmaker") != book or alternatives.get("captured_at") != row["captured_at"]:
            return None
        payload = alternatives.get("payload")
    else:
        return None
    parts = row["selection_id"].split(":")
    if len(parts) != 3 or parts[0] != market or parts[1] not in ("over","under"):
        return None
    line, side, odds = float(row["market_line"]), parts[1], float(row["odds"])
    pairs = quote_lines(payload, market, book)
    if (line != float(parts[2]) or line not in pairs or odds < 1.5
            or round(pairs[line][side], 3) != round(odds, 3)):
        return None
    scores = card["set_score"]["value"]
    distribution = defaultdict(float)
    if market == "sets":
        for score, p in scores.items():
            distribution[sum(map(int, score.split(":")))] += p
    else:
        distribution = {int(n): p for n,p in card["other_projections"]["value"]["total_games"].items()}
    if not math.isclose(sum(distribution.values()), 1, abs_tol=1e-6):
        return None
    edge_floor = float(os.getenv("BLINQ_POINT_SG_MIN_EDGE", "0"))
    if not 0 <= edge_floor <= 1:
        raise ValueError("Invalid SG edge floor")
    board, tips = [], []
    for line_value, prices in sorted(pairs.items()):
        push = distribution.get(line_value, 0)
        if push >= 1:
            continue
        over = sum(p for n,p in distribution.items() if n > line_value)
        under = sum(p for n,p in distribution.items() if n < line_value)
        vig = sum(1 / price for price in prices.values())
        for direction, p in (("over", over), ("under", under)):
            price = prices[direction]
            conditional = p / (over + under)
            implied = 1 / price / vig
            edge = conditional - implied
            item = {"line":line_value, "side":direction, "odds":price, "p_win":p, "p_push":push,
                    "fair_odds":1/conditional if conditional else None, "market_no_vig":implied, "edge":edge}
            board.append(item)
            if (card["data_quality"] == "supported" and conditional >= floor and price >= 1.5
                    and edge > 0 and edge >= edge_floor and conditional * price > 1):
                tips.append(item)
    return {"market":market, "source":source, "bookmaker":book, "quoted_at":row["captured_at"],
            "frozen_at":frozen.isoformat(), "confidence_floor":floor, "edge_floor":edge_floor,
            "set_score":scores, "board":board, "current":{"line":line,"side":side,"odds":odds},
            "point":max(tips, key=lambda t:t["edge"], default=None)}


def grade(bet, actual):
    gap = actual - bet["line"]
    if not gap:
        return "push", 0.
    if (gap > 0) == (bet["side"] == "over"):
        return "win", bet["odds"] - 1
    return "loss", -1.


def summary(rows, days):
    """Flat-unit return per stake including refunds; CI resamples calendar days."""
    wins = sum(status == "win" for day,status,profit in rows)
    losses = sum(status == "loss" for day,status,profit in rows)
    n = len(rows)
    by_day = defaultdict(list)
    for day,status,profit in rows:
        by_day[day].append(profit)
    blocks = [(len(values), sum(values)) for _,values in sorted(by_day.items())]
    samples = []
    if len(blocks) >= 2:
        rng = Random(54)
        for _ in range(1000):
            sample = rng.choices(blocks, k=len(blocks))
            samples.append(sum(p for _,p in sample)/sum(k for k,_ in sample))
        samples.sort()
    hit_ci = None
    decided = wins + losses
    if decided:
        rate = wins / decided
        z = 1.96
        center = rate + z*z/(2*decided)
        radius = z*math.sqrt(rate*(1-rate)/decided + z*z/(4*decided**2))
        hit_ci = [max(0., (center-radius)/(1+z*z/decided)), min(1., (center+radius)/(1+z*z/decided))]
    return {"hit_ci":hit_ci, "n":n, "push":n-wins-losses, "hit":wins/(wins+losses) if wins+losses else None,
            "yield":sum(p for _,_,p in rows)/n if n else None,
            "per_day":n/days, "ci":[samples[24],samples[974]] if samples else None}
