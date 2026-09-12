from __future__ import annotations

import math

from ..utils import clamp


def elo_expected(rating_a: float, rating_b: float) -> float:
    """Standard Elo expected score for player A."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def dynamic_k(matches_played: int, base: float = 32.0, floor: float = 12.0) -> float:
    """High learning rate for new players, gradually stabilising with experience."""
    value = base / (1.0 + 0.16 * math.log1p(max(matches_played, 0)))
    return clamp(value, floor, base)


def update_elo(
    rating_a: float,
    rating_b: float,
    score_a: float,
    matches_a: int,
    matches_b: int,
    multiplier: float = 1.0,
) -> tuple[float, float]:
    expected_a = elo_expected(rating_a, rating_b)
    delta_a = dynamic_k(matches_a) * multiplier * (score_a - expected_a)
    delta_b = dynamic_k(matches_b) * multiplier * ((1.0 - score_a) - (1.0 - expected_a))
    return rating_a + delta_a, rating_b + delta_b
