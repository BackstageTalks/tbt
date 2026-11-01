"""ACES-only real-quote policy, independent of the existing model's player ranking.

An independently priced bookmaker O/U is evaluated against the selected player's
frozen expected ACE count. No fabricated price or price at another line is used.
"""
from __future__ import annotations

from tbt.services.projection_odds import _player_ou_probability


def eligible_aces_offer(mean: float, lines: list[dict], *, min_probability: float = 0.60,
                        min_odds: float = 1.50) -> dict | None:
    evaluated = []
    for item in lines:
        try:
            line = float(item["line"])
            p_over = _player_ou_probability(float(mean), "aces", line)
        except (ValueError, TypeError, KeyError):
            continue
        for side in ("over", "under"):
            try:
                odds = float(item[side])
            except (KeyError, ValueError, TypeError):
                continue
            probability = p_over if side == "over" else 1 - p_over
            ev = probability * odds - 1
            if probability >= min_probability and odds >= min_odds and ev >= 0:
                evaluated.append((ev, probability, odds, side, line, item))
    if not evaluated:
        return None
    ev, probability, odds, side, line, item = max(evaluated, key=lambda c:(c[0], c[1], c[2]))
    return {"ev": ev, "probability": probability, "odds": odds, "side": side,
            "line": line, "source_market": item}
