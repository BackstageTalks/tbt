"""Historical conditional projection for LIVE second-set comeback candidates.

This is intentionally separate from the pre-match Match Winner model.  It only
uses settled structured set scores that existed before the current UTC day and
estimates P(favourite wins set 2 | favourite lost set 1).
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any

EXCLUDED_STATUSES = {
    "retired", "walkover", "walk over", "cancelled", "canceled",
    "abandoned", "interrupted", "suspended", "postponed",
}
MODEL_VERSION = "live-second-set-comeback-v1"


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _weighted_rate(samples: list[tuple[datetime, float]], now: datetime, *, half_life_days: float = 180.0) -> tuple[float | None, float, int]:
    weighted: list[tuple[float, float]] = []
    for when, value in samples:
        days = max(0.0, (now - when).total_seconds() / 86400.0)
        weight = 0.5 ** (days / half_life_days)
        weighted.append((float(value), weight))
    if not weighted:
        return None, 0.0, 0
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        return None, 0.0, 0
    return sum(value * weight for value, weight in weighted) / total, total, len(weighted)


def _shrink(rate: float | None, effective_n: float, baseline: float, strength: float) -> float:
    if rate is None or effective_n <= 0:
        return baseline
    return (rate * effective_n + baseline * strength) / (effective_n + strength)


def _player_ids(row: dict[str, Any]) -> tuple[str, str]:
    p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    return str(p1.get("id") or "").strip(), str(p2.get("id") or "").strip()


def _favorite_id(row: dict[str, Any]) -> str:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    selected = str(betting.get("selection_id") or row.get("winner_id") or "").strip()
    if selected:
        return selected
    p1, p2 = _player_ids(row)
    p1_obj = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    p2_obj = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    a, b = _num(p1_obj.get("probability")), _num(p2_obj.get("probability"))
    if a is not None and b is not None:
        return p1 if a >= b else p2
    return ""


def _build_index(history, cutoff: datetime):
    lost_first: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    won_first_conceded: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    lost_first_surface: dict[tuple[str, str], list[tuple[datetime, float]]] = defaultdict(list)
    baseline_samples: list[tuple[datetime, float]] = []
    usable_matches = 0

    for match in history:
        when = match.scheduled_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        else:
            when = when.astimezone(timezone.utc)
        if when >= cutoff or str(match.status or "").strip().lower() in EXCLUDED_STATUSES:
            continue
        stats = match.stats if isinstance(match.stats, dict) else {}
        p1_first = _num(stats.get("p1_first_set_won"))
        p2_first = _num(stats.get("p2_first_set_won"))
        p1_second = _num(stats.get("p1_second_set_won"))
        p2_second = _num(stats.get("p2_second_set_won"))
        if None in {p1_first, p2_first, p1_second, p2_second}:
            continue
        if round(p1_first + p2_first) != 1 or round(p1_second + p2_second) != 1:
            continue
        p1, p2 = str(match.player1_id), str(match.player2_id)
        surface = str(match.surface or "unknown").lower()
        if p1_first < p2_first:
            loser, leader = p1, p2
            outcome = float(p1_second > p2_second)
        else:
            loser, leader = p2, p1
            outcome = float(p2_second > p1_second)
        lost_first[loser].append((when, outcome))
        won_first_conceded[leader].append((when, outcome))
        lost_first_surface[(loser, surface)].append((when, outcome))
        baseline_samples.append((when, outcome))
        usable_matches += 1
    return lost_first, won_first_conceded, lost_first_surface, baseline_samples, usable_matches


def annotate_live_second_set_projections(
    feed: dict[str, Any],
    history,
    *,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach a conditional second-set probability to internal PRIME rows.

    The projection is computed at refresh time so the runtime LIVE scanner does
    not need access to the full historical corpus.
    """
    if now.tzinfo is None:
        raise ValueError("annotate_live_second_set_projections requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lost, conceded, surface_lost, baseline_samples, usable = _build_index(history, cutoff)
    baseline_rate, baseline_eff_n, baseline_n = _weighted_rate(baseline_samples, now, half_life_days=365.0)
    baseline = 0.50 if baseline_rate is None else max(0.20, min(0.80, baseline_rate))

    result = deepcopy(feed)
    rows = result.get("prime_picks") if isinstance(result.get("prime_picks"), list) else []
    annotated = []
    projected = 0
    for source in rows:
        if not isinstance(source, dict):
            continue
        row = deepcopy(source)
        fav = _favorite_id(row)
        p1, p2 = _player_ids(row)
        opp = p2 if fav == p1 else p1 if fav == p2 else ""
        surface = str(row.get("surface") or "unknown").lower()
        fav_rate, fav_eff, fav_n = _weighted_rate(lost.get(fav, []), now)
        opp_rate, opp_eff, opp_n = _weighted_rate(conceded.get(opp, []), now)
        surf_rate, surf_eff, surf_n = _weighted_rate(surface_lost.get((fav, surface), []), now)

        # Player-specific conditional behaviour is the primary signal.  The
        # opponent close-out history is secondary.  Both are Bayesian-shrunk
        # toward the historical population baseline to avoid sparse extremes.
        fav_est = _shrink(fav_rate, fav_eff, baseline, 8.0)
        opp_est = _shrink(opp_rate, opp_eff, baseline, 8.0)
        if fav_n and opp_n:
            estimate = 0.68 * fav_est + 0.32 * opp_est
        elif fav_n:
            estimate = fav_est
        elif opp_n:
            estimate = 0.60 * baseline + 0.40 * opp_est
        else:
            estimate = baseline
        if surf_n >= 4:
            surf_est = _shrink(surf_rate, surf_eff, baseline, 5.0)
            estimate = 0.80 * estimate + 0.20 * surf_est

        total_n = fav_n + opp_n
        evidence = min(1.0, (fav_eff + 0.5 * opp_eff) / 18.0)
        estimate = baseline + (estimate - baseline) * (0.55 + 0.45 * evidence)
        estimate = max(0.20, min(0.85, estimate))
        quality = "high" if fav_n >= 12 and total_n >= 20 else "medium" if fav_n >= 6 and total_n >= 10 else "low"
        row["live_second_set_projection"] = {
            "schema": 1,
            "model": MODEL_VERSION,
            "conditional": "win_set_2_given_lost_set_1",
            "probability": round(estimate, 4),
            "population_baseline": round(baseline, 4),
            "favorite_samples": fav_n,
            "opponent_closeout_samples": opp_n,
            "favorite_surface_samples": surf_n,
            "quality": quality,
            "cutoff_utc": cutoff.isoformat(),
        }
        projected += 1
        annotated.append(row)
    result["prime_picks"] = annotated
    return result, {
        "schema": 1,
        "model": MODEL_VERSION,
        "projection_only": True,
        "conditional": "win_set_2_given_lost_set_1",
        "history_matches_with_set2": usable,
        "population_samples": baseline_n,
        "population_effective_samples": round(baseline_eff_n, 2),
        "population_baseline": round(baseline, 4),
        "prime_rows_projected": projected,
        "cutoff_utc": cutoff.isoformat(),
    }
