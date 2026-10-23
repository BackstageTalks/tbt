"""Opt-in, research-only point-in-time DIL evidence features and reliability gate.

No database writer, production selector integration, probability recalibration or
training side effects. Callers must supply independently reviewed canonical IDs
and a real source-availability timestamp; this layer never guesses links.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable, Mapping


@dataclass(frozen=True)
class HistoricalEvidence:
    canonical_match_id: str
    tour: str
    player_id: str
    surface: str
    completed_at: datetime
    available_at: datetime
    expected_recorded_at: datetime
    won: bool
    expected_win: float  # historical *pre-match* expected probability
    service_points: int | None = None
    first_in: int | None = None
    first_won: int | None = None
    second_won: int | None = None
    opponent_service_points: int | None = None
    opponent_first_won: int | None = None
    opponent_second_won: int | None = None
    bp_saved: int | None = None
    bp_faced: int | None = None
    opponent_bp_saved: int | None = None
    opponent_bp_faced: int | None = None
    reviewed_cdb_link: bool = False


def _aware(t: datetime) -> None:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps are required")


def _rate(won: int | None, total: int | None) -> tuple[int, int] | None:
    if won is None or total is None:
        return None
    if isinstance(won, bool) or isinstance(total, bool) or not isinstance(won, int) or not isinstance(total, int):
        raise ValueError("Raw service / break-point counters must be integers")
    if total < 0 or won < 0 or won > total:
        raise ValueError("Inconsistent won/total counts")
    return (won, total) if total > 0 else None


def _sum_known(a: int | None, b: int | None) -> int | None:
    return a + b if a is not None and b is not None else None


def _second_attempts(r: HistoricalEvidence) -> int | None:
    if r.service_points is None or r.first_in is None:
        return None
    if r.first_in > r.service_points or r.first_in < 0:
        raise ValueError("Invalid first serve attempts")
    return r.service_points - r.first_in


def _counts(r: HistoricalEvidence) -> dict[str, tuple[int, int] | None]:
    serve_won = _sum_known(r.first_won, r.second_won)
    opp_won = _sum_known(r.opponent_first_won, r.opponent_second_won)
    if opp_won is not None and r.opponent_service_points is not None:
        ret_won = r.opponent_service_points - opp_won
    else:
        ret_won = None
    if r.bp_faced is not None and r.bp_saved is not None:
        _rate(r.bp_saved, r.bp_faced)
    if r.opponent_bp_faced is not None and r.opponent_bp_saved is not None:
        _rate(r.opponent_bp_saved, r.opponent_bp_faced)
    convert = (r.opponent_bp_faced - r.opponent_bp_saved
               if r.opponent_bp_faced is not None and r.opponent_bp_saved is not None else None)
    return {
        "serve": _rate(serve_won, r.service_points),
        "return": _rate(ret_won, r.opponent_service_points),
        "second_serve": _rate(r.second_won, _second_attempts(r)),
        "bp_save": _rate(r.bp_saved, r.bp_faced),
        "bp_convert": _rate(convert, r.opponent_bp_faced),
    }


def _surface(surface: str) -> str:
    s = str(surface or "unknown").strip().lower()
    return "hard" if s == "indoor_hard" else s


def player_features(records: Iterable[HistoricalEvidence], *, player_id: str, tour: str,
                    surface: str, issued_at: datetime, limit: int = 20) -> dict:
    """PIT features from at most 20 prior completed canonical matches.

    A date-only historical match must not inform another match on the same UTC
    day. Source availability is mandatory to rule out post-hoc enrichment.
    """
    _aware(issued_at)
    if tour.lower() not in {"atp", "wta"} or not player_id or limit < 1:
        raise ValueError("Explicit ATP/WTA canonical player and positive window required")
    prior: list[HistoricalEvidence] = []
    seen: set[str] = set()
    cutoff_day = issued_at.astimezone(timezone.utc).date()
    for r in records:
        if r.player_id != player_id or r.tour.lower() != tour.lower():
            continue
        if r.reviewed_cdb_link is not True or not r.canonical_match_id:
            raise ValueError("Unreviewed or missing canonical CDB identity")
        _aware(r.completed_at)
        _aware(r.available_at)
        _aware(r.expected_recorded_at)
        if not isinstance(r.won, bool) or r.expected_recorded_at >= r.completed_at:
            raise ValueError("Outcome and prior probability require verified pre-result evidence")
        if r.completed_at > r.available_at:
            raise ValueError("Source stats marked available before match completion")
        if r.completed_at.astimezone(timezone.utc).date() >= cutoff_day or r.available_at > issued_at:
            continue
        if r.canonical_match_id in seen:
            raise ValueError("Duplicate linked canonical match for a player")
        seen.add(r.canonical_match_id)
        if not math.isfinite(r.expected_win) or not 0 <= r.expected_win <= 1:
            raise ValueError("Missing verified pre-match opponent expectation")
        _counts(r)  # validate even if the row falls outside the recent window
        prior.append(r)
    prior.sort(key=lambda r: (r.completed_at, r.canonical_match_id), reverse=True)
    selected = prior[:limit]
    same = [r for r in selected if _surface(r.surface) == _surface(surface)
            and _surface(surface) != "unknown"]

    def residual(rows):
        weights = [0.5 ** ((issued_at - r.completed_at).total_seconds() / 86400 / 90)
                   for r in rows]
        return sum(w * (float(r.won) - r.expected_win) for r, w in zip(rows, weights)) / (6.0 + sum(weights))

    # Shrink surface residual to the already historical overall recent prior.
    global_form = residual(selected)
    surface_residual = residual(same)
    mix = len(same) / (len(same) + 8.0)
    form = mix * surface_residual + (1 - mix) * global_form
    aggregated = {}
    coverage = {}
    for metric in ("serve", "return", "second_serve", "bp_save", "bp_convert"):
        numerator = denominator = n = 0
        for r in selected:
            pair = _counts(r)[metric]
            if pair is not None:
                numerator += pair[0]
                denominator += pair[1]
                n += 1
        aggregated[metric + "_rate"] = numerator / denominator if denominator else None
        coverage[metric] = n
    return {
        "canonical_player_id": player_id, "tour": tour.lower(),
        "matches_recent": len(selected), "matches_surface": len(same),
        "opponent_adjusted_form": global_form,
        "surface_opponent_adjusted_form": form,
        "stats": aggregated, "covered_matches": coverage,
    }


def reliability_gate(left: Mapping, right: Mapping,
                     model_probabilities: Iterable[float]) -> dict:
    """Research-only evidence filter; score is NOT a calibrated win probability."""
    ps = tuple(model_probabilities)
    if len(ps) < 2 or any(not isinstance(p, (int, float)) or not math.isfinite(p)
                          or not 0 <= p <= 1 for p in ps):
        return {"eligible": False, "evidence_score": 0.0,
                "reasons": ["missing_or_invalid_model_disagreement"]}
    if left.get("tour") != right.get("tour") or left.get("canonical_player_id") == right.get("canonical_player_id"):
        raise ValueError("Players require distinct canonical IDs on the same tour")
    reasons = []
    n = min(int(left.get("matches_recent") or 0), int(right.get("matches_recent") or 0))
    surf = min(int(left.get("matches_surface") or 0), int(right.get("matches_surface") or 0))
    if n < 10: reasons.append("sparse_recent_history")
    if surf < 5: reasons.append("sparse_surface_history")
    rates = ("serve", "return", "second_serve", "bp_save", "bp_convert")
    cover = min(
        min(int(f.get("covered_matches", {}).get(k) or 0) for f in (left, right))
        for k in rates
    )
    if cover < 5: reasons.append("insufficient_verified_stat_coverage")
    gap = max(ps) - min(ps)
    if n < 0 or surf < 0 or cover < 0 or surf > n or cover > n:
        raise ValueError("Contradictory evidence counts")
    if gap > 0.12: reasons.append("model_disagreement")
    # Transparent evidence index; not trained/calibrated on the holdout.
    score = round(0.25 * min(n / 20, 1.0) + 0.2 * min(surf / 10, 1.0)
                  + 0.35 * min(cover / 10, 1.0)
                  + 0.2 * max(0.0, 1.0 - gap / 0.20), 4)
    if score < 0.72: reasons.append("low_evidence_score")
    return {"eligible": not reasons, "evidence_score": score,
            "reasons": reasons, "recent_min": n, "surface_min": surf,
            "stat_coverage_min": cover, "model_probability_gap": round(gap, 4)}
