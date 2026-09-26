"""Point-in-time Sets / Games projection shortlist.

The layer uses only structured historical set/game scores recorded before the
current UTC day. It is intentionally projection-only until BlinQ validates and
backtests a dependable pre-match Sets/Games price/line mapping.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any

from ..match_format import (
    exact_best_of_from_score_stats,
    provider_best_of_from_context,
    infer_best_of,
)


EXCLUDED_STATUSES = {
    "retired", "walkover", "walk over", "cancelled", "canceled",
    "abandoned", "interrupted", "suspended", "postponed",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _weighted_stats(samples: list[dict[str, Any]], field: str, now: datetime) -> tuple[float | None, float | None, int]:
    weighted: list[tuple[float, float]] = []
    for sample in samples:
        value = _number(sample.get(field))
        when = sample.get("scheduled_at")
        if value is None or not isinstance(when, datetime):
            continue
        days = max(0.0, (now - when).total_seconds() / 86400.0)
        weight = 0.5 ** (days / 150.0)
        weighted.append((value, weight))
    if not weighted:
        return None, None, 0
    total_w = sum(w for _, w in weighted)
    mean = sum(v * w for v, w in weighted) / total_w
    variance = sum(w * (v - mean) ** 2 for v, w in weighted) / total_w if len(weighted) > 1 else 0.0
    return mean, max(0.0, variance), len(weighted)


def _weighted_mean(samples: list[dict[str, Any]], field: str, now: datetime) -> tuple[float | None, int]:
    mean, _, count = _weighted_stats(samples, field, now)
    return mean, count


def _shrink(value: float, n: int, baseline: float, strength: float = 8.0) -> float:
    weight = n / (n + strength) if n > 0 else 0.0
    return weight * value + (1.0 - weight) * baseline


def _long_match(total_sets: float, best_of: int) -> float:
    if best_of == 3:
        return float(total_sets >= 3)
    if best_of == 5:
        return float(total_sets >= 4)
    return 0.0


def _history_index(history, cutoff: datetime):
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    baselines: dict[tuple[str, int], dict[str, list[float]]] = defaultdict(
        lambda: {"games": [], "sets": [], "long": []}
    )
    score_matches = 0
    exact_from_score = 0
    provider_confirmed = 0
    format_conflicts = 0
    unsupported_scores = 0

    for match in history:
        if match.scheduled_at >= cutoff:
            continue
        if str(match.status or "").strip().lower() in EXCLUDED_STATUSES:
            continue
        stats = match.stats if isinstance(match.stats, dict) else {}
        total_sets = _number(stats.get("total_sets"))
        total_games = _number(stats.get("total_games"))
        if total_sets is None or total_games is None:
            continue
        if total_sets < 2 or total_games < 12:
            continue

        # Historical format is never inferred from tour/tournament. A finished
        # structured score proves BO3/BO5 exactly. If the raw provider payload
        # also publishes bestOf, both facts must agree or the row is rejected.
        score_best_of, _score_source = exact_best_of_from_score_stats(stats)
        if score_best_of not in {3, 5}:
            unsupported_scores += 1
            continue
        raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        provider_best_of = provider_best_of_from_context(raw)
        if provider_best_of in {3, 5} and provider_best_of != score_best_of:
            format_conflicts += 1
            continue
        best_of = provider_best_of or score_best_of
        if provider_best_of:
            provider_confirmed += 1
        else:
            exact_from_score += 1

        long_value = _long_match(total_sets, best_of)
        key = (str(match.tour or "").lower(), best_of)
        baselines[key]["games"].append(total_games)
        baselines[key]["sets"].append(total_sets)
        baselines[key]["long"].append(long_value)
        score_matches += 1
        common = {
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc),
            "surface": str(match.surface or "unknown").lower(),
            "best_of": best_of,
            "tour": str(match.tour or "").lower(),
            "total_games": total_games,
            "total_sets": total_sets,
            "long_match": long_value,
        }
        by_player[str(match.player1_id)].append(common)
        by_player[str(match.player2_id)].append(common)

    baseline_values: dict[tuple[str, int], dict[str, float]] = {}
    for key, values in baselines.items():
        games = values["games"]
        sets = values["sets"]
        long = values["long"]
        if games and sets and long:
            baseline_values[key] = {
                "games": sum(games) / len(games),
                "sets": sum(sets) / len(sets),
                "long": sum(long) / len(long),
                "n": float(len(games)),
            }
    diagnostics = {
        "exact_from_finished_score": exact_from_score,
        "provider_confirmed": provider_confirmed,
        "provider_score_conflicts_rejected": format_conflicts,
        "unsupported_structured_scores_rejected": unsupported_scores,
    }
    return by_player, baseline_values, score_matches, diagnostics


def _player_estimate(
    player_id: str,
    histories: dict[str, list[dict[str, Any]]],
    field: str,
    now: datetime,
    *,
    tour: str,
    surface: str,
    best_of: int,
    baseline: float,
) -> dict[str, Any] | None:
    rows = [row for row in histories.get(str(player_id), []) if row.get("best_of") == best_of and row.get("tour") == tour]
    mean, variance, n = _weighted_stats(rows, field, now)
    if mean is None or n < 6:
        return None
    estimate = _shrink(mean, n, baseline)
    surface_rows = [row for row in rows if surface and surface != "unknown" and row.get("surface") == surface]
    surface_mean, surface_variance, surface_n = _weighted_stats(surface_rows, field, now)
    if surface_mean is not None and surface_n >= 4:
        surface_est = _shrink(surface_mean, surface_n, baseline, strength=5.0)
        estimate = 0.75 * estimate + 0.25 * surface_est
        if surface_variance is not None:
            variance = 0.75 * float(variance or 0.0) + 0.25 * float(surface_variance)
    return {
        "estimate": estimate,
        "variance": max(0.0, float(variance or 0.0)),
        "samples": n,
        "surface_samples": surface_n,
    }


def _sets_card(
    row: dict[str, Any],
    p1_total: dict[str, Any],
    p2_total: dict[str, Any],
    p1_long: dict[str, Any],
    p2_long: dict[str, Any],
    *,
    best_of: int,
    baseline_sets: float,
    baseline_long: float,
) -> dict[str, Any] | None:
    # Selection confidence remains a probability of the O/U direction, while
    # `projection` is now the expected TOTAL number of sets in the match.  The
    # previous v3 payload exposed direction confidence (for example 0.90) as if
    # it were "0.9 sets", which was semantically wrong in Results.
    raw_probability = max(0.02, min(0.98, (p1_long["estimate"] + p2_long["estimate"]) / 2.0))
    depth_n = min(int(p1_long["samples"]), int(p2_long["samples"]), int(p1_total["samples"]), int(p2_total["samples"]))
    depth = min(1.0, depth_n / 24.0)
    surface_depth = min(
        int(p1_long["surface_samples"]), int(p2_long["surface_samples"]),
        int(p1_total["surface_samples"]), int(p2_total["surface_samples"]),
    )
    surface_factor = min(1.0, surface_depth / 8.0) if surface_depth else 0.0
    evidence = min(1.0, 0.85 * math.sqrt(depth) + 0.15 * surface_factor)

    adjusted_probability = 0.5 + (raw_probability - 0.5) * evidence
    is_over = adjusted_probability > 0.5
    selected_probability = adjusted_probability if is_over else 1.0 - adjusted_probability
    selected_probability = min(0.90, selected_probability)
    probability_distance = abs(adjusted_probability - 0.5)
    if selected_probability < 0.60:
        return None

    line = 2.5 if best_of == 3 else 3.5
    selection = f"{'Over' if is_over else 'Under'} {line:.1f} Sets"
    expected_sets = (float(p1_total["estimate"]) + float(p2_total["estimate"])) / 2.0
    # Keep the public projection physically possible for the match format.
    expected_sets = max(2.0 if best_of == 3 else 3.0, min(float(best_of), expected_sets))
    # The displayed total and the selected O/U direction must never contradict
    # each other. This is mathematically exact for BO3; for BO5 it also gives us
    # a conservative fail-closed guard when mean total sets and long-match rate
    # disagree because 4- and 5-set matches share the same >3.5 indicator.
    if (expected_sets > line) != is_over:
        return None
    projection_gap = abs(expected_sets - line)

    card = deepcopy(row)
    card.pop("market_publication_candidates", None)
    card.pop("betting", None)
    card.pop("match_winner_market", None)
    card.update({
        "market": "sets",
        "market_type": "Total Sets Projection",
        "projection_scope": "match_total",
        "projection_metric": "sets",
        "projection_kind": "match_total_sets",
        "projection_label": "Zápas · Sety",
        "pick": selection,
        "selection": selection,
        "selection_id": f"sets:{'over' if is_over else 'under'}:{line:.1f}",
        "projection": round(expected_sets, 2),
        "projection_unit": "sets",
        "raw_long_match_probability": round(raw_probability, 4),
        "evidence_adjusted_probability": round(adjusted_probability, 4),
        "reference_projection": round(line, 2),
        "projection_gap": round(projection_gap, 2),
        "projection_confidence": round(selected_probability, 4),
        "probability": None,
        "odds": None,
        "edge": None,
        "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "sets-games-projection-v4",
        "projection_source": "historical_structured_scores",
        "projection_samples": {
            "player1": int(p1_total["samples"]), "player2": int(p2_total["samples"]),
            "player1_surface": int(p1_total["surface_samples"]), "player2_surface": int(p2_total["surface_samples"]),
        },
        "baseline_projection": round(float(baseline_sets), 3),
        "baseline_long_match_probability": round(float(baseline_long), 4),
        "best_of": best_of,
        "data_depth": round(depth, 4),
        "projection_score": selected_probability * (1.0 + probability_distance * 2.0),
    })
    return card

def _games_card(
    row: dict[str, Any],
    p1: dict[str, Any],
    p2: dict[str, Any],
    *,
    best_of: int,
    baseline: float,
    bookmaker_line: float | None = None,
) -> dict[str, Any] | None:
    estimate = (p1["estimate"] + p2["estimate"]) / 2.0
    # Odds-first: the probability must refer to the real offered O/U line,
    # never to a historical mean that no bookmaker is offering.
    reference = float(bookmaker_line) if bookmaker_line is not None else baseline
    deviation = estimate - reference
    min_deviation = 1.4 if best_of == 3 else 2.2
    if abs(deviation) < min_deviation:
        return None
    direction = "High" if deviation > 0 else "Low"
    selection = f"{direction} Total Games"
    depth_n = min(int(p1["samples"]), int(p2["samples"]))
    depth = min(1.0, depth_n / 24.0)
    surface_depth = min(int(p1["surface_samples"]), int(p2["surface_samples"]))
    surface_factor = min(1.0, surface_depth / 8.0) if surface_depth else 0.0

    v1, v2 = float(p1.get("variance") or 0.0), float(p2.get("variance") or 0.0)
    # Future match totals remain noisy even with large historical samples.  The
    # old v2 divided variance by sample count (uncertainty of the mean), which
    # could make a 1.5-game deviation look nearly certain.  Use predictive
    # variance of a new match instead, with a conservative format-specific floor.
    predictive_floor = 3.5 if best_of == 3 else 5.5
    predictive_variance = max(predictive_floor ** 2, 0.25 * (v1 + v2))
    se = math.sqrt(predictive_variance)
    z = abs(deviation) / se if se > 0 else 0.0
    raw_direction_probability = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    evidence = min(1.0, 0.85 * math.sqrt(depth) + 0.15 * surface_factor)
    confidence = 0.5 + (raw_direction_probability - 0.5) * evidence
    confidence = max(0.5, min(0.90, confidence))
    if confidence < 0.60:
        return None

    card = deepcopy(row)
    card.pop("market_publication_candidates", None)
    card.pop("betting", None)
    card.pop("match_winner_market", None)
    card.update({
        "market": "games", "market_type": "Total Games Projection",
        "projection_scope": "match_total", "projection_metric": "games",
        "projection_kind": "match_total_games", "projection_label": "Zápas · Gamy",
        "pick": selection, "selection": selection, "selection_id": f"games:{direction.lower()}",
        "projection": round(float(estimate), 2), "projection_unit": "games",
        "reference_projection": round(float(reference), 2),
        "projection_gap": round(abs(float(deviation)), 2),
        "projection_direction": direction.lower(),
        "projection_confidence": round(confidence, 4),
        "raw_direction_confidence": round(raw_direction_probability, 4),
        "projection_uncertainty": round(se, 3),
        "probability": None, "odds": None, "edge": None, "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "sets-games-projection-v4",
        "projection_source": "historical_structured_scores",
        "projection_samples": {
            "player1": int(p1["samples"]), "player2": int(p2["samples"]),
            "player1_surface": int(p1["surface_samples"]), "player2_surface": int(p2["surface_samples"]),
        },
        "baseline_projection": round(float(baseline), 2),
        "market_line": round(float(bookmaker_line), 2) if bookmaker_line is not None else None,
        "best_of": best_of, "data_depth": round(depth, 4),
        "projection_score": confidence * (1.0 + min(2.0, abs(deviation) / (4.0 if best_of == 3 else 6.0))),
    })
    return card



def _adaptive_confidence_select(
    cards: list[dict[str, Any]],
    *,
    target_count: int = 10,
    start_probability: float = 0.80,
    minimum_probability: float = 0.52,
    step: float = 0.02,
) -> tuple[list[dict[str, Any]], float | None, dict[str, int]]:
    """Fill toward the daily target by relaxing confidence only.

    Data depth, sample-size, surface and signal/gap guards are applied before
    this helper and are never bypassed. If the hard floor still produces fewer
    than the target, the smaller honest set is returned.
    """
    minimum=max(0.0,min(1.0,float(minimum_probability)))
    threshold=max(minimum,min(1.0,float(start_probability)))
    thresholds=[]
    while threshold > minimum + 1e-9:
        thresholds.append(round(threshold, 4))
        threshold -= max(0.001,float(step))
    thresholds.append(round(minimum,4))
    thresholds=sorted(set(thresholds),reverse=True)
    selected=[];applied=None;counts={}
    for floor in thresholds:
        selected=[row for row in cards if float(row.get("projection_confidence") or 0.0) >= floor]
        counts[f"{floor:.2f}"]=len(selected)
        applied=floor
        if len(selected)>=max(1,int(target_count)):
            break
    return selected,applied,counts

def select_sg_picks(
    history,
    predictions: list[dict[str, Any]],
    *,
    now: datetime,
    per_market_limit: int = 10,
    total_limit: int = 20,
    target_count: int = 10,
    available_markets_by_event: dict[str, set[str]] | None = None,
    bookmaker_lines_by_event: dict[str, dict[str, list[float]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if now.tzinfo is None:
        raise ValueError("select_sg_picks requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    histories, baselines, score_matches, history_format = _history_index(history, cutoff)

    by_market: dict[str, list[dict[str, Any]]] = {"sets": [], "games": []}
    eligible = 0
    missing_best_of = 0
    inferred_upcoming_best_of = 0
    upcoming_inference_sources: dict[str, int] = defaultdict(int)
    missing_baseline = 0
    for row in predictions:
        p1_obj = row.get("player1") if isinstance(row.get("player1"), dict) else {}
        p2_obj = row.get("player2") if isinstance(row.get("player2"), dict) else {}
        p1_id, p2_id = str(p1_obj.get("id") or ""), str(p2_obj.get("id") or "")
        if not p1_id or not p2_id:
            continue
        declared_source = str(row.get("best_of_source") or "").strip().lower()
        provider_fact = declared_source in {"provider", "provider_payload", "provider_detail"}
        best_of, best_of_source = infer_best_of(
            explicit=row.get("best_of") if provider_fact else None,
            tour=row.get("tour"),
            tournament=row.get("tournament"),
            tournament_level=row.get("competition") or row.get("tournament_level"),
            round_name=row.get("round") or row.get("round_name"),
        )
        if best_of not in {3, 5}:
            missing_best_of += 1
            continue
        effective_row = row
        if best_of_source != "provider":
            inferred_upcoming_best_of += 1
            upcoming_inference_sources[best_of_source] += 1
            effective_row = deepcopy(row)
            effective_row["best_of"] = best_of
            effective_row["best_of_source"] = best_of_source
        tour = str(row.get("tour") or "").lower()
        surface = str(row.get("surface") or "unknown").lower()
        baseline = baselines.get((tour, best_of))
        if not baseline:
            missing_baseline += 1
            continue
        eligible += 1
        event_id = str(row.get("event_id") or "")
        offered = (available_markets_by_event.get(event_id, set())
                   if available_markets_by_event is not None else {"games", "sets"})

        p1_sets_total = _player_estimate(
            p1_id, histories, "total_sets", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["sets"]),
        )
        p2_sets_total = _player_estimate(
            p2_id, histories, "total_sets", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["sets"]),
        )
        p1_sets_long = _player_estimate(
            p1_id, histories, "long_match", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["long"]),
        )
        p2_sets_long = _player_estimate(
            p2_id, histories, "long_match", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["long"]),
        )
        if "sets" in offered and p1_sets_total and p2_sets_total and p1_sets_long and p2_sets_long:
            card = _sets_card(
                effective_row, p1_sets_total, p2_sets_total, p1_sets_long, p2_sets_long,
                best_of=best_of, baseline_sets=float(baseline["sets"]),
                baseline_long=float(baseline["long"]),
            )
            if card:
                # SETS needs the exact published O/U line, typically 2.5 or
                # 3.5, to exist on the bookmaker's two-sided board.
                offered_lines = (bookmaker_lines_by_event or {}).get(event_id, {}).get("sets", [])
                if bookmaker_lines_by_event is None or any(
                    abs(float(line) - float(card["reference_projection"])) < .01
                    for line in offered_lines
                ):
                    by_market["sets"].append(card)

        p1_games = _player_estimate(
            p1_id, histories, "total_games", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["games"]),
        )
        p2_games = _player_estimate(
            p2_id, histories, "total_games", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["games"]),
        )
        if "games" in offered and p1_games and p2_games:
            # Evaluate the *actual bookmaker lines* first. An older model-only
            # run still evaluates its historical baseline as before.
            market_lines = ((bookmaker_lines_by_event or {}).get(event_id, {}).get("games", [])
                            if bookmaker_lines_by_event is not None else [None])
            # Closest to the model's projection, rather than an extreme
            # alternate low-price line. Require the existing hard signal and
            # predictive-variance floors for every possible offered line.
            estimated_total = (float(p1_games["estimate"]) + float(p2_games["estimate"])) / 2
            for line in sorted(market_lines, key=lambda x: abs(float(x) - estimated_total)):
                card = _games_card(
                    effective_row, p1_games, p2_games, best_of=best_of,
                    baseline=float(baseline["games"]), bookmaker_line=line,
                )
                if card:
                    by_market["games"].append(card)
                    break

    for market in by_market:
        by_market[market].sort(
            key=lambda row: (
                float(row.get("projection_score") or 0.0),
                float(row.get("projection_confidence") or 0.0),
                float(row.get("projection_gap") or 0.0),
            ),
            reverse=True,
        )
        by_market[market] = by_market[market][: max(0, int(per_market_limit))]

    # SETS and GAMES must fill independently. A combined adaptive threshold can
    # let one market satisfy the target before the sibling market reaches its own
    # honest confidence floor, which made valid SETS/GAMES disappear from the UI.
    selected_by_market: dict[str, list[dict[str, Any]]] = {}
    applied_floors: dict[str, float | None] = {}
    tier_counts_by_market: dict[str, dict[str, int]] = {}
    per_market_target = max(1, min(int(per_market_limit), int(target_count)))
    for market in ("sets", "games"):
        selected, floor, counts = _adaptive_confidence_select(
            by_market[market], target_count=per_market_target, minimum_probability=0.60
        )
        selected_by_market[market] = selected[: max(0, int(per_market_limit))]
        applied_floors[market] = None if floor is None else float(floor)
        tier_counts_by_market[market] = counts

    combined = selected_by_market["sets"] + selected_by_market["games"]
    combined.sort(key=lambda row: float(row.get("projection_score") or 0.0), reverse=True)
    combined = combined[: max(0, int(total_limit))]
    for row in combined:
        row.pop("projection_score", None)

    baseline_report = {
        f"{tour}_bo{best_of}": {
            "games": round(float(values["games"]), 3),
            "sets": round(float(values["sets"]), 3),
            "long_match_probability": round(float(values["long"]), 4),
            "n": int(values["n"]),
        }
        for (tour, best_of), values in sorted(baselines.items())
    }
    return combined, {
        "schema": 5,
        "model": "sets-games-projection-v4",
        "cutoff_utc": cutoff.isoformat(),
        "projection_only": True,
        "odds_backed": False,
        "settlement_enabled": True,
        "history_matches_with_structured_score": score_matches,
        "history_best_of_inferred": 0,
        "history_best_of_inference_sources": {},
        "history_format_facts": history_format,
        "eligible_upcoming_matches": eligible,
        "upcoming_best_of_inferred": inferred_upcoming_best_of,
        "upcoming_best_of_inference_sources": dict(upcoming_inference_sources),
        "missing_best_of": missing_best_of,
        "missing_baseline": missing_baseline,
        "sets_selected": sum(row.get("market") == "sets" for row in combined),
        "games_selected": sum(row.get("market") == "games" for row in combined),
        "selected": len(combined),
        "per_market_limit": int(per_market_limit),
        "total_limit": int(total_limit),
        "target_count": int(target_count),
        "target_count_per_market": per_market_target,
        "candidate_cards": {market: len(by_market[market]) for market in ("sets", "games")},
        "adaptive_confidence_floor": applied_floors,
        "adaptive_tier_counts": tier_counts_by_market,
        "confidence_caps": {"sets": 0.90, "games": 0.90},
        "uncertainty_model": "future_match_predictive_variance",
        "fill_policy": "independent_market_fill_evidence_adjusted_hard_floor_0.60",
        "baselines": baseline_report,
    }
