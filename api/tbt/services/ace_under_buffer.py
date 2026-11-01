"""Minimum and preferred real-market cushions for player Aces UNDER bets.

Only applies to prospective player-aces UNDER contracts. Historical settled
publications, Most Aces superiority, Over, DF and sets/games are untouched.
Projection is never adjusted and no bookmaker line is manufactured.
"""
from __future__ import annotations

import math


def ace_under_margins(projection: float) -> tuple[float, float]:
    """Return (required, preferred) absolute ace cushions."""
    value = float(projection)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Aces projection must be finite and nonnegative")
    if value < 4.0:
        return 1.0, 2.0
    if value <= 8.0:
        return 1.5, 2.0
    return 2.0, 3.0


def ace_under_eligible(projection: float, line: float) -> bool:
    """An actual offered UNDER line must clear the minimum cushion."""
    try:
        estimate, offered = float(projection), float(line)
        required, _ = ace_under_margins(estimate)
    except (ValueError, TypeError, OverflowError):
        return False
    return math.isfinite(offered) and offered >= 0 and offered - estimate >= required - 1e-9


def ace_under_preferred(projection: float, line: float) -> bool:
    """Preferred cushion is a ranking preference, never a fabricated quote."""
    if not ace_under_eligible(projection, line):
        return False
    _, preferred = ace_under_margins(projection)
    return float(line) - float(projection) >= preferred - 1e-9
