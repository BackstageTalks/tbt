"""Frozen v18 selection experiment baseline at 958019b (research only).

Keep the existing raw-vs-depth ablation reproducible when production policy changes.
Do not import this module from the application or use it to publish selections.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from tbt.services.price_integrity import extreme_winner_price_inversion, post_start_winner_quote, unsubstantiated_high_confidence_winner
from research.legacy_top_rank_v18 import _rank_full_slate_top
from tbt.services.market_selection import (
    _depth, _exclusive_section_assignment, _fill_to_minimum, _is_close_odds_value, _market_card, _market_odds_difference, _number, _overall_samples, _passes_candidate_gate, _prime_display_rank, _selection_identity, _surface_samples, _value_qualification_audit
)

MATCH_WINNER_MARKET_NAMES = {
    "full time",
    "fulltime",
    "match winner",
    "matchwinner",
    "winner",
    "moneyline",
}
SECTION_PRIORITY = ("value", "top_daily", "prime")
PUBLICATION_MIN_PROBABILITY = 0.65
PRIME_TOP_CORE_PROBABILITY = 0.68
PRIME_TOP_FALLBACK_PROBABILITY = 0.65
TOP_DYNAMIC_FALLBACK_MIN_PROBABILITY = 0.60
TOP_DYNAMIC_FALLBACK_TIERS = ()
PRIME_MIN_PROBABILITY = PRIME_TOP_CORE_PROBABILITY
PRIME_DAILY_FLOOR = PRIME_TOP_FALLBACK_PROBABILITY
PRIME_PREFERRED_PROBABILITY = 0.80
PRIME_FALLBACK_PROBABILITIES = (0.78, 0.76, 0.74, 0.72, 0.70, 0.68)
PRIME_TARGET_COUNT = 10
PRIME_MIN_COUNT = 5
PRIME_MIN_DATA_DEPTH = 0.80
PRIME_MIN_SURFACE_MATCHES = 5
PRIME_MAX_NEGATIVE_EV = -1.0
PRIME_PREFERRED_MIN_ODDS = 1.01
PRIME_PREFERRED_MAX_ODDS = 1.49
PRIME_MAX_ODDS_EXCLUSIVE = 1.50
PRIME_LIMIT = 30
TOP_PREFERRED_PROBABILITY = 0.80
TOP_SECONDARY_PROBABILITY = 0.78
TOP_STANDARD_PROBABILITY = 0.75
TOP_FALLBACK_PROBABILITIES = ()
TOP_MIN_PROBABILITY = TOP_DYNAMIC_FALLBACK_MIN_PROBABILITY
TOP_TARGET_COUNT = 3
TOP_MIN_COUNT = 3
TOP_MIN_DATA_DEPTH = 0.80
TOP_MIN_SURFACE_MATCHES = 5
TOP_MIN_ODDS: float | None = 1.50
TOP_FALLBACK_MIN_ODDS = 1.50
TOP_MIN_EDGE: float | None = None
TOP_MIN_EXPECTED_VALUE: float | None = None
TOP_LIMIT: int | None = 3
TOP_BACKUP_MIN_DATA_DEPTH = 0.75
TOP_BACKUP_MIN_SURFACE_MATCHES = 3
VALUE_MIN_PROBABILITY = PUBLICATION_MIN_PROBABILITY
VALUE_MIN_DATA_DEPTH = 0.75
VALUE_MIN_SURFACE_MATCHES = 3
VALUE_MIN_ODDS = 1.80
VALUE_MAX_ODDS_DIFFERENCE = 0.15
VALUE_MIN_EDGE = 0.0
VALUE_MIN_EXPECTED_VALUE = -1.0
VALUE_LIMIT: int | None = None
VALUE_TARGET_COUNT = 10
VALUE_MIN_COUNT = 5
VALUE_FALLBACK_TIERS = ()

def select_market_sections(
    predictions: list[dict[str, Any]],
    *,
    prime_min_probability: float = PRIME_MIN_PROBABILITY,
    prime_min_data_depth: float = PRIME_MIN_DATA_DEPTH,
    prime_min_surface_matches: int = PRIME_MIN_SURFACE_MATCHES,
    prime_max_negative_ev: float = PRIME_MAX_NEGATIVE_EV,
    prime_limit: int | None = PRIME_LIMIT,
    top_min_probability: float = TOP_MIN_PROBABILITY,
    top_min_data_depth: float = TOP_MIN_DATA_DEPTH,
    top_min_surface_matches: int = TOP_MIN_SURFACE_MATCHES,
    top_min_odds: float | None = TOP_MIN_ODDS,
    top_min_edge: float | None = TOP_MIN_EDGE,
    top_min_expected_value: float | None = TOP_MIN_EXPECTED_VALUE,
    top_limit: int | None = TOP_LIMIT,
    value_min_probability: float = VALUE_MIN_PROBABILITY,
    value_min_data_depth: float = VALUE_MIN_DATA_DEPTH,
    value_min_surface_matches: int = VALUE_MIN_SURFACE_MATCHES,
    value_min_odds: float = VALUE_MIN_ODDS,
    value_min_edge: float = VALUE_MIN_EDGE,
    value_min_expected_value: float = VALUE_MIN_EXPECTED_VALUE,
    value_limit: int | None = VALUE_LIMIT,
    section_priority: tuple[str, ...] = SECTION_PRIORITY,
    ace_picks: list[dict[str, Any]] | None = None,
    sg_picks: list[dict[str, Any]] | None = None,
    doubles_picks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish existing TOP/PRIME/VALUE with unchanged markets and price contracts.

    TOP ranks the entire safe priced Match Winner slate, aiming for three
    quality-qualified picks. VALUE remains higher priority; ACES is untouched.
    """
    cards = [
        card for row in predictions
        if isinstance(row, dict)
        and row.get("prediction_family") != "doubles"
        and (card := _market_card(row)) is not None
    ]

    prime_core_floor = max(PRIME_TOP_CORE_PROBABILITY, float(prime_min_probability))
    top_core_floor = max(TOP_MIN_PROBABILITY, float(top_min_probability))
    fallback_floor = PRIME_TOP_FALLBACK_PROBABILITY
    top_fallback_floor = max(TOP_DYNAMIC_FALLBACK_MIN_PROBABILITY, float(top_min_probability))
    value_floor = max(PUBLICATION_MIN_PROBABILITY, float(value_min_probability))
    value_audit = _value_qualification_audit(
        predictions,
        min_probability=value_floor,
        min_data_depth=value_min_data_depth,
        min_surface_matches=value_min_surface_matches,
        min_odds=value_min_odds,
        max_odds_difference=VALUE_MAX_ODDS_DIFFERENCE,
    )

    value_qualified: list[dict[str, Any]] = []
    prime_core: list[dict[str, Any]] = []
    prime_fallback: list[dict[str, Any]] = []
    top_core: list[dict[str, Any]] = []
    top_fallback: list[dict[str, Any]] = []

    extreme_inversion_quarantined = 0
    market_conflict_missing_rank_quarantined = 0
    post_start_quote_quarantined = 0
    for card in cards:
        odds = _number(card.get("odds"))
        if odds is None:
            continue
        probability = _number(card.get("probability")) or 0.0
        # A >50 percentage-point disagreement is an integrity exception,
        # not a change to model probability or bookmaker source priority.
        if extreme_winner_price_inversion(probability, odds):
            extreme_inversion_quarantined += 1
            continue
        if post_start_winner_quote(card):
            post_start_quote_quarantined += 1
            continue
        if unsubstantiated_high_confidence_winner(card):
            market_conflict_missing_rank_quarantined += 1
            continue

        if (
            odds >= float(value_min_odds)
            and _passes_candidate_gate(
                card, min_probability=value_floor,
                min_data_depth=value_min_data_depth,
                min_surface_matches=value_min_surface_matches,
            )
            and _is_close_odds_value(card)
        ):
            value_qualified.append(card)

        if odds < PRIME_MAX_ODDS_EXCLUSIVE and _passes_candidate_gate(
            card, min_probability=fallback_floor,
            min_data_depth=prime_min_data_depth,
            min_surface_matches=prime_min_surface_matches,
        ):
            (prime_core if probability >= prime_core_floor else prime_fallback).append(card)

        top_core_odds = max(TOP_FALLBACK_MIN_ODDS, float(top_min_odds or TOP_MIN_ODDS or 1.50))
        if odds >= top_core_odds and _passes_candidate_gate(
            card, min_probability=top_core_floor,
            min_data_depth=top_min_data_depth,
            min_surface_matches=top_min_surface_matches,
        ):
            tagged = deepcopy(card)
            tagged["selection_tier"] = "ranked_core"
            top_core.append(tagged)
        elif odds >= top_core_odds and _passes_candidate_gate(
            card, min_probability=top_core_floor,
            min_data_depth=min(float(top_min_data_depth), TOP_BACKUP_MIN_DATA_DEPTH),
            min_surface_matches=min(int(top_min_surface_matches), TOP_BACKUP_MIN_SURFACE_MATCHES),
        ):
            tagged = deepcopy(card)
            tagged["selection_tier"] = "ranked_backup"
            top_fallback.append(tagged)

    rank = lambda card: (
        _number(card.get("probability")) or 0.0,
        _depth(card),
        min(_surface_samples(card)),
        min(_overall_samples(card)),
    )
    value_qualified.sort(key=rank, reverse=True)

    # VALUE retains exclusive priority. TOP ranks the remaining full priced slate.
    value_ids = {_selection_identity(card) for card in value_qualified}
    top_core = [card for card in top_core if _selection_identity(card) not in value_ids]
    top_fallback = [card for card in top_fallback if _selection_identity(card) not in value_ids]

    prime_qualified, prime_fallback_added = _fill_to_minimum(
        prime_core, prime_fallback, minimum_count=PRIME_MIN_COUNT, rank_key=rank
    )
    top_qualified, top_fallback_added, top_fallback_applied = _rank_full_slate_top(
        top_core, top_fallback, target=TOP_TARGET_COUNT, minimum=TOP_MIN_COUNT,
    )

    selected, duplicate_removed, limited_out = _exclusive_section_assignment(
        {"value": value_qualified, "prime": prime_qualified, "top_daily": top_qualified},
        priority=section_priority,
        limits={"value": value_limit, "prime": prime_limit, "top_daily": top_limit},
    )
    value = selected.get("value", [])
    prime = _prime_display_rank(selected.get("prime", []))
    top = selected.get("top_daily", [])

    selected_identities = [_selection_identity(card) for card in (prime + top + value)]
    if len(selected_identities) != len(set(selected_identities)):
        raise ValueError("Market section exclusivity invariant failed")
    if any((_number(card.get("probability")) or 0.0) + 1e-12 < PRIME_TOP_FALLBACK_PROBABILITY for card in prime):
        raise ValueError("Prime fallback probability floor invariant failed")
    if any((_number(card.get("probability")) or 0.0) + 1e-12 < top_core_floor for card in top):
        raise ValueError("Top fallback probability floor invariant failed")
    if any((_number(card.get("probability")) or 0.0) + 1e-12 < PUBLICATION_MIN_PROBABILITY for card in value):
        raise ValueError("Value probability floor invariant failed")
    if any((_number(card.get("odds")) or 0.0) >= PRIME_MAX_ODDS_EXCLUSIVE for card in prime):
        raise ValueError("Prime odds bucket invariant failed")
    if any((_number(card.get("odds")) or 0.0) < TOP_FALLBACK_MIN_ODDS for card in top):
        raise ValueError("Top odds floor invariant failed")

    value_diffs = [_market_odds_difference(card) for card in value]
    return {
        "top200_picks": [],  # Retired product: empty compatibility field; never issue new picks.
        "top_daily_picks": top,
        "prime_picks": prime,
        "value_picks": value,
        "ace_picks": deepcopy(ace_picks or []),
        "sg_picks": deepcopy(sg_picks or []),
        "doubles_picks": deepcopy(doubles_picks or []),
        "market_selection": {
            "schema": 16,
            "selection_policy": "active_value_top_prime_rank_v18",
            "selection_counts": {
                "priced_match_winner_rows": len(cards),
                "extreme_price_inversion_quarantined": extreme_inversion_quarantined,
                "market_conflict_missing_rank_quarantined": market_conflict_missing_rank_quarantined,
                "post_start_quote_quarantined": post_start_quote_quarantined,
                "prime_core_68_plus": len(prime_core),
                "top_core_80_plus_after_value_priority": sum((_number(c.get("probability")) or 0.0) >= 0.80 for c in top_core),
                "top_core_68_plus_after_value_priority": len(top_core),  # legacy metadata key
                "prime_fallback_65_679_added": prime_fallback_added,
                "top_fallback_added": top_fallback_added,
                "top_fallback_applied": top_fallback_applied,
                "value_qualified_before_exclusivity": len(value_qualified),
                "prime": len(prime), "top_daily": len(top), "value": len(value),
                "duplicates_removed": sum(duplicate_removed.values()),
                "limited_out": sum(limited_out.values()),
                "daily_minimum_target": TOP_MIN_COUNT,
                "daily_preferred_target": TOP_MIN_COUNT,
                "all_qualifying_above_active_tier": False,
                "active_top_probability_floor": top_fallback_applied["min_probability"],
                "top_daily_shortfall": max(0, TOP_MIN_COUNT-len(top)),
                "minimum_shortfall": {
                    "prime": max(0, PRIME_MIN_COUNT-len(prime)),
                    "top_daily": max(0, TOP_MIN_COUNT-len(top)),
                    "value": max(0, VALUE_MIN_COUNT-len(value)),
                },
            },
            "exclusive_assignment": {
                "enabled": True,
                "priority": list(section_priority),
                "dedupe_key": "market:betting_day:event_id:selection_id",
                "duplicates_removed_by_section": duplicate_removed,
                "limited_out_by_section": limited_out,
                "limit_aware": True,
            },
            "current_outputs": (["match_winner"] + (["doubles_match_winner"] if doubles_picks else []) + (["aces_projection", "double_faults_projection"] if ace_picks else []) + (["sets_projection", "games_projection"] if sg_picks else [])),
            "pending_outputs": ["aces_odds", "double_faults_odds", "sets_odds", "games_odds"],
            "odds_backed": True,
            "odds_backed_outputs": ["match_winner"] + (["doubles_match_winner"] if doubles_picks else []),
            "projection_only_outputs": ((["aces_projection", "double_faults_projection"] if ace_picks else []) + (["sets_projection", "games_projection"] if sg_picks else [])),
            "main_candidate_rule": {
                "core_probability": PRIME_TOP_CORE_PROBABILITY,
                "prime_fallback_probability": PRIME_TOP_FALLBACK_PROBABILITY,
                "top_fallback_probability_floor": TOP_MIN_PROBABILITY,
                "top_probability_tiers": [TOP_MIN_PROBABILITY],
                "top_dynamic_fallback_tiers": [
                    {"min_probability": p, "min_odds": o} for p, o in TOP_DYNAMIC_FALLBACK_TIERS
                ],
                "fallback_only_if_section_below": TOP_MIN_COUNT,
                "probability_basis": "blinq_probability=data_depth_shrunk_calibrated_model_probability",
                "edge_filter": False,
            },
            "prime_rule": {
                "objective": "75pct_probability_percentile_25pct_odds_percentile",
                "probability_basis": "blinq_probability",
                "display_ranking_only": True,
                "display_weights": {"probability_percentile": 0.75, "odds_percentile": 0.25},
                "eligibility_pool_unchanged": True,
                "core_min_probability": prime_core_floor,
                "fallback_min_probability": fallback_floor,
                "fallback_only_if_core_count_below": PRIME_MIN_COUNT,
                "min_data_depth": float(prime_min_data_depth),
                "min_surface_matches_each": int(prime_min_surface_matches),
                "min_odds": None,
                "max_odds_exclusive": PRIME_MAX_ODDS_EXCLUSIVE,
                "edge_ev_role": "diagnostic_only",
                "limit": prime_limit,
                "sort": "probability_desc_then_data_depth_then_sample_depth",
            },
            "top_daily_rule": {
                "product_label": "Top Bets",
                "objective": "ranked_market_model_consensus",
                "probability_basis": "blinq_probability",
                "core_min_probability": top_core_floor,
                "fallback_min_probability": top_fallback_floor,
                "probability_tiers": [TOP_MIN_PROBABILITY],
                "daily_minimum_target": TOP_MIN_COUNT,
                "all_qualifying_above_active_tier": False,
                "no_forced_fill": True,
                "observed_pick_count": len(top),
                "fallback_only_if_core_count_below": TOP_MIN_COUNT,
                "dynamic_fallback": False,
                "dynamic_fallback_tiers": [
                    {"min_probability": p, "min_odds": o} for p, o in TOP_DYNAMIC_FALLBACK_TIERS
                ],
                "applied_fallback": top_fallback_applied,
                "min_data_depth": float(top_min_data_depth),
                "min_surface_matches_each": int(top_min_surface_matches),
                "requires_odds": True,
                "core_min_odds": float(top_min_odds or TOP_MIN_ODDS or 1.50),
                "fallback_min_odds": TOP_FALLBACK_MIN_ODDS,
                "min_odds": TOP_FALLBACK_MIN_ODDS,
                "value_priority_exclusion": True,
                "edge_ev_role": "diagnostic_only",
                "limit": top_limit,
                "sort": "quality_consensus_then_evidence",
                "ranked_full_slate": True,
                "daily_preferred_count": TOP_TARGET_COUNT,
                "backup_min_data_depth": TOP_BACKUP_MIN_DATA_DEPTH,
                "backup_min_surface_matches_each": TOP_BACKUP_MIN_SURFACE_MATCHES,
            },
            "doubles_rule": {
                "model": "DOUBLES-ELO-v1",
                "separate_from_singles": True,
                "requires_member_identity": True,
                "requires_real_match_winner_odds": True,
                "published": len(doubles_picks or []),
            },
            "value_audit": value_audit,
            "value_rule": {
                "objective": "probability_plus_close_odds",
                "probability_basis": "blinq_probability",
                "min_probability": value_floor,
                "min_data_depth": float(value_min_data_depth),
                "min_surface_matches_each": int(value_min_surface_matches),
                "min_odds": float(value_min_odds),
                "max_two_way_odds_difference": VALUE_MAX_ODDS_DIFFERENCE,
                "odds_difference_formula": "abs(o1-o2)/mean(o1,o2)",
                "edge_ev_role": "diagnostic_only",
                "assignment_priority": 1,
                "limit": value_limit,
                "sort": "probability_desc_then_data_depth_then_sample_depth",
                "max_selected_odds_difference": max((d for d in value_diffs if d is not None), default=None),
            },
        },
    }
