"""Conservative tennis set/game score normalisation.

TennisApi uses SofaScore-like ``homeScore``/``awayScore`` objects for settled
matches. This adapter consumes only structured per-set fields (period1..period5)
and never parses a human score string. That keeps historical Sets/Games features
point-in-time and auditable while failing closed on unsupported score shapes.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import ProviderError


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or abs(number - round(number)) > 1e-9:
        return None
    return int(round(number))


def _score_object(event: dict[str, Any], key: str) -> dict[str, Any]:
    value = event.get(key)
    return value if isinstance(value, dict) else {}


def _set_pair(home: int, away: int) -> bool:
    """Return True only for a conventional completed tennis set score."""
    high, low = max(home, away), min(home, away)
    if high == 6 and 0 <= low <= 4:
        return True
    if high == 7 and low in {5, 6}:
        return True
    return False


def _sets_from_summary(score: dict[str, Any]) -> int | None:
    for key in ("current", "display", "norm"):
        value = _int_value(score.get(key))
        if value is not None:
            return value
    return None


def parse_event_score(
    payload: dict[str, Any],
    *,
    home_is_player1: bool,
    best_of: int | None = None,
) -> dict[str, float]:
    """Extract whole-match Sets/Games facts from a finished event payload.

    Returns an empty dict when the provider exposes no usable structured score.
    If score fields are present but contradictory, raises ``ProviderError`` so
    the caller can preserve the raw sample and avoid manufacturing data.
    """
    if not isinstance(payload, dict):
        return {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    home = _score_object(event, "homeScore")
    away = _score_object(event, "awayScore")
    if not home or not away:
        return {}

    period_pairs: list[tuple[int, int]] = []
    for index in range(1, 6):
        h_raw, a_raw = home.get(f"period{index}"), away.get(f"period{index}")
        h, a = _int_value(h_raw), _int_value(a_raw)
        if h is None and a is None:
            continue
        if h is None or a is None:
            raise ProviderError(f"Incomplete structured set score at period{index}")
        # Finished singles matches should not contain an unfinished partial set.
        # Values >7 are likely point scores / match-tiebreak shapes and are not
        # safe to reinterpret as games, so fail closed.
        if not _set_pair(h, a):
            raise ProviderError(f"Unsupported completed set score {h}-{a} at period{index}")
        period_pairs.append((h, a))

    if not period_pairs:
        return {}

    home_sets = sum(h > a for h, a in period_pairs)
    away_sets = sum(a > h for h, a in period_pairs)
    summary_home, summary_away = _sets_from_summary(home), _sets_from_summary(away)
    if summary_home is not None and summary_home != home_sets:
        raise ProviderError("homeScore summary conflicts with per-set score")
    if summary_away is not None and summary_away != away_sets:
        raise ProviderError("awayScore summary conflicts with per-set score")
    if home_sets == away_sets:
        raise ProviderError("Finished tennis score has no set winner")

    if best_of is not None:
        try:
            best_of_int = int(best_of)
        except (TypeError, ValueError):
            best_of_int = 0
        if best_of_int in {3, 5}:
            required = best_of_int // 2 + 1
            if max(home_sets, away_sets) != required:
                raise ProviderError("Finished score does not match best-of format")

    home_games = sum(h for h, _ in period_pairs)
    away_games = sum(a for _, a in period_pairs)
    first_home_win = period_pairs[0][0] > period_pairs[0][1]
    total_sets = len(period_pairs)
    tiebreak_sets = sum({h, a} == {6, 7} for h, a in period_pairs)
    straight_sets = int(min(home_sets, away_sets) == 0)
    deciding_set = 0
    if best_of in {3, 5}:
        deciding_set = int(total_sets == int(best_of))
    elif total_sets in {3, 5}:
        deciding_set = 1

    home_values = {
        "sets_won": float(home_sets),
        "games_won": float(home_games),
        "first_set_won": float(first_home_win),
    }
    away_values = {
        "sets_won": float(away_sets),
        "games_won": float(away_games),
        "first_set_won": float(not first_home_win),
    }
    p1, p2 = (home_values, away_values) if home_is_player1 else (away_values, home_values)

    return {
        "p1_sets_won": p1["sets_won"],
        "p2_sets_won": p2["sets_won"],
        "p1_games_won": p1["games_won"],
        "p2_games_won": p2["games_won"],
        "p1_first_set_won": p1["first_set_won"],
        "p2_first_set_won": p2["first_set_won"],
        "total_sets": float(total_sets),
        "total_games": float(home_games + away_games),
        "tiebreak_sets": float(tiebreak_sets),
        "straight_sets": float(straight_sets),
        "deciding_set": float(deciding_set),
    }
