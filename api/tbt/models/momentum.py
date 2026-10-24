"""Candidate-only change in opponent-adjusted form, using prior UTC days."""
import math
from datetime import timezone

MOMENTUM_FEATURE_NAMES = ["opponent_momentum_diff"]


def opponent_momentum(recent, now):
    if now.tzinfo is None:
        raise ValueError("Momentum requires aware timestamps")
    day = now.astimezone(timezone.utc).date()
    short, old = [], []
    for item in recent:
        if item.played_at.tzinfo is None:
            continue
        age = (day - item.played_at.astimezone(timezone.utc).date()).days
        if not 1 <= age <= 90:
            continue
        won, expected = float(item.won), float(item.expected)
        if (not math.isfinite(expected) or not 0 <= expected <= 1
                or won not in (0., 1.)):
            continue
        (short if age <= 30 else old).append(won - expected)
    # Require evidence in both non-overlapping windows; shrink noisy samples.
    if len(short) < 3 or len(old) < 3:
        return 0.
    return sum(short)/(len(short)+6.) - sum(old)/(len(old)+6.)
