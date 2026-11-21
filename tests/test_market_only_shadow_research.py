"""Isolated market-only research, never a live selector."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tbt.services.market_only_shadow_research import (
    calibrate_market_only, load_shadow_params, rank_shadow_candidates,
    shadow_card, append_only_shadow_rows, prepare_all_singles_shadow_rows,
)

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_shadow_params(ROOT / "research/market_only_shadow/params_2026-11-20.json")
START = "2026-11-21T15:00:00Z"


def card(*, model=.85, fair=.80, event="e1", level="ATP",
         cap="2026-11-21T12:00:00Z", issue="2026-11-21T12:15:00Z",
         category="TOP"):
    return {
        "event_id": event, "tour": "ATP", "competition": level,
        "tournament": "ATP 250", "model_version": "test-v1",
        "prediction_family": "singles", "category": category,
        "player1": {"id": "p1"}, "player2": {"id": "p2"}, "winner_id": "p1",
        "scheduled_at": START, "created_at": issue, "probability": model,
        "betting": {"market": "match_winner", "selection_id": "p1",
                    "captured_at": cap, "fair_implied_probability": fair,
                    "odds": 1.5},
    }


def fixture(*, event="e1", fair1=.8, fair2=.2,
            quote="2026-11-21T10:00:00Z", issued="2026-11-21T10:30:00Z",
            tour="ATP"):
    return {
        "event_id": event, "model_version": "v1", "tour": tour,
        "prediction_family": "singles", "player1_id": "a",
        "player2_id": "b", "model_player1_probability": .79,
        "model_captured_at": "2026-11-21T09:00:00Z",
        "scheduled_at": START, "fair_player1": fair1, "fair_player2": fair2,
        "market_captured_at": quote, "issued_at": issued,
        "bookmaker": "book1", "source_provenance": "snapshot-v1",
    }


def test_original_public_probability_is_not_modified():
    original = card()
    baseline = deepcopy(original)
    out = shadow_card(original, PARAMS)
    assert original == baseline
    assert out["probability"] == baseline["probability"]
    assert out["shadow_research"]["shadow_probability"] == pytest.approx(
        calibrate_market_only(.8, PARAMS))
    assert out["shadow_research"]["shadow_eligible_for_actual_publication"] is False


def test_calibration_monotonic_and_no_added_market_rank_information():
    xs = [.51, .6, .7, .75, .8, .95]
    ys = [calibrate_market_only(x, PARAMS) for x in xs]
    assert all(a < b for a, b in zip(ys, ys[1:]))
    assert calibrate_market_only(.501, PARAMS) < .5


def test_a1_a2_a3_variants_are_independent():
    cards = [card(model=.85, fair=.82, event="good"),
             card(model=.85, fair=.70, event="low"),
             card(model=.85, fair=.81, event="large_gap"),
             card(model=.85, fair=.40, event="opposing")]
    assert [x["event_id"] for x in rank_shadow_candidates(
        cards, PARAMS, variant="A1_market_rank_veto")] == [
            "good", "large_gap", "low"]
    assert [x["event_id"] for x in rank_shadow_candidates(
        cards, PARAMS, variant="A2_market_min_0_75")] == [
            "good", "large_gap"]
    assert [x["event_id"] for x in rank_shadow_candidates(
        cards, PARAMS, variant="A3_gap_0_10")] == [
            "good", "large_gap"]
    assert [x["event_id"] for x in rank_shadow_candidates(
        cards, PARAMS, variant="A1_A2_A3_combined")] == [
            "good", "large_gap"]


def test_missing_or_unverified_fair_fallback_never_becomes_public():
    for category in ("TOP", "Value", "ACCA"):
        failed = (
            card(fair=None, category=category),
            card(cap=START, category=category),
            card(issue=START, category=category),
            card(cap="2026-11-21T12:00:00", category=category),
            card(cap="2026-11-21T12:30:00Z",
                 issue="2026-11-21T12:15:00Z", category=category),
        )
        for original in failed:
            out = shadow_card(original, PARAMS)["shadow_research"]
            assert out["shadow_fair_missing_or_invalid"] is True
            assert out["shadow_probability"] == pytest.approx(.85)
            assert not any(out["shadow_decisions"].values())


def test_gap_is_not_itf_only_in_research_cohorts():
    for level in ("ATP", "WTA", "Challenger"):
        x = card(model=.87, fair=.76, level=level)
        d = shadow_card(x, PARAMS)["shadow_research"]["shadow_decisions"]
        assert d["A3_gap_0_10"] is False
        assert d["A2_market_min_0_75"] is True


def test_ambiguous_selection_and_duplicate_rejected():
    bad = card()
    bad["betting"]["selection_id"] = "unknown"
    with pytest.raises(ValueError):
        shadow_card(bad, PARAMS)
    with pytest.raises(ValueError):
        rank_shadow_candidates([card(), card()], PARAMS,
                               variant="A1_market_rank_veto")


def test_append_only_preserves_old_and_rejects_conflict():
    prior = {"event_id": "1", "model_version": "v1", "player1_id": "a",
             "player2_id": "b", "scheduled_at": START, "tour": "ATP",
             "status": "pending", "fair_player1": .72}
    revised = deepcopy(prior)
    revised["fair_player1"] = .70
    out = append_only_shadow_rows([prior], [revised])
    assert len(out) == 1 and out[0]["fair_player1"] == .72
    assert prior["fair_player1"] == .72
    revised["player2_id"] = "conflict"
    with pytest.raises(ValueError, match="Conflicting"):
        append_only_shadow_rows([prior], [revised])
    with pytest.raises(ValueError):
        append_only_shadow_rows([], [{**prior, "status": "settled"}])


def test_frozen_gate_cannot_be_relaxed(tmp_path):
    path = ROOT / "research/market_only_shadow/params_2026-11-20.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["activation_approved"] = True
    modified = tmp_path / "unapproved.json"
    modified.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        load_shadow_params(modified)
    settings["activation_approved"] = False
    settings["selector_experiments"]["market_min_fair"] = .61
    modified.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        load_shadow_params(modified)


def test_full_slate_keeps_unpriced_and_never_invents_fair():
    data = prepare_all_singles_shadow_rows(
        [fixture(), fixture(event="e2", fair1=None, fair2=None)], PARAMS)
    assert len(data) == 2
    assert data[0]["shadow_market_missing"] is False
    assert data[1]["shadow_market_missing"] is True
    assert data[1]["shadow_player1_probability"] == .79
    assert data[1]["fair_player1"] is None
    assert data[1]["status"] == "pending"
    assert data[0]["shadow_read_only_no_publication"]


def test_full_slate_needs_two_sided_prematch_fair():
    failures = [
        fixture(fair2=.25), fixture(quote=START), fixture(issued=START),
        fixture(quote="2026-11-21T10:00:00"),
        fixture(issued="2026-11-21T09:30:00Z"),
    ]
    for sample in failures:
        out = prepare_all_singles_shadow_rows([sample], PARAMS)[0]
        assert out["shadow_market_missing"] is True
        assert out["shadow_player1_probability"] == .79


def test_full_slate_identity_and_pit_guard():
    with pytest.raises(ValueError):
        prepare_all_singles_shadow_rows([fixture(), fixture()], PARAMS)
    late = fixture()
    late["model_captured_at"] = START
    with pytest.raises(ValueError):
        prepare_all_singles_shadow_rows([late], PARAMS)


def test_a0_all_a1_a2_a3_vetoes_still_emit_minimum_five():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    pool = [card(event=f"reject-{i}", model=.85, fair=.35 + i*.01)
            for i in range(9)]
    original = deepcopy(pool)
    selected = select_daily_shadow_picks(pool, PARAMS, n_min=5)
    assert len(selected) == 5
    assert all(row["selection_tier"] == "T2" for row in selected)
    assert all(row["selection_basis"] == "rank_market" for row in selected)
    assert all(row["shadow_research"]["shadow_eligible_for_actual_publication"] is False
               for row in selected)
    assert pool == original


def test_a0_no_fair_returns_five_ordered_model_fallbacks():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    pool = [card(event=f"fallback-{i}", model=.61 + .02*i, fair=None)
            for i in range(8)]
    selected = select_daily_shadow_picks(pool, PARAMS)
    assert len(selected) == 5
    assert [row["event_id"] for row in selected] == [
        "fallback-7", "fallback-6", "fallback-5", "fallback-4", "fallback-3"]
    assert all(row["selection_tier"] == "T3"
               and row["selection_basis"] == "fallback_model" for row in selected)


def test_a0_smaller_than_minimum_returns_all_candidates():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    pool = [card(event=f"short-{i}", model=.85, fair=.35) for i in range(3)]
    assert len(select_daily_shadow_picks(pool, PARAMS, n_min=5)) == 3


def test_a0_deterministic_per_utc_day_and_all_t0_above_minimum():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    import random
    pool = [card(event=f"T0-{i}", model=.81, fair=.80) for i in range(7)]
    pool += [card(event=f"T2-{i}", model=.88, fair=.44) for i in range(4)]
    late = card(event="next-day", model=.82, fair=None)
    late["scheduled_at"] = "2026-11-22T15:00:00Z"
    pool.append(late)
    canonical = select_daily_shadow_picks(pool, PARAMS)
    assert len(canonical) == 8
    assert [x["event_id"] for x in canonical[:7]] == [
        f"T0-{i}" for i in range(7)]
    assert canonical[-1]["shadow_selection_day_utc"] == "2026-11-22"
    shuffled = list(pool)
    random.Random(20261121).shuffle(shuffled)
    assert [(x["event_id"], x["selection_tier"], x["selection_basis"])
            for x in select_daily_shadow_picks(shuffled, PARAMS)] == [
        (x["event_id"], x["selection_tier"], x["selection_basis"])
        for x in canonical]


def test_a0_tiers_prioritized_and_publication_never_modified():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    pool = [
        card(event="T0", fair=.8, model=.83),
        card(event="T1", fair=.60, model=.86),
        card(event="T2", fair=.40, model=.88),
        card(event="T3", fair=None, model=.95),
    ]
    before = deepcopy(pool)
    selected = select_daily_shadow_picks(pool, PARAMS, n_min=5)
    assert [x["selection_tier"] for x in selected] == ["T0","T1","T2","T3"]
    assert [x["selection_basis"] for x in selected] == [
        "rank_market","rank_market","rank_market","fallback_model"]
    assert pool == before
    for row in selected:
        assert row["shadow_research"]["shadow_eligible_for_actual_publication"] is False
        assert row["probability"] == before[
            [x["event_id"] for x in before].index(row["event_id"])]["probability"]


def test_opener_is_explicit_variant_not_default_and_never_wta_verified():
    from tbt.services.market_only_shadow_research import calibrate_market_only
    assert PARAMS["opener_fallback"]["claimed_fit_n"] == 36972
    assert PARAMS["opener_fallback"]["independent_fit_reproduced"] is False
    assert PARAMS["opener_fallback"]["wta_verified"] is False
    assert calibrate_market_only(.8, PARAMS) != calibrate_market_only(
        .8, PARAMS, variant="opener")
    with pytest.raises(ValueError):
        calibrate_market_only(.8, PARAMS, variant="unknown")

def test_a0_rejects_duplicate_event_on_both_selected_sides():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    first = card(event="same-event", fair=.8, model=.85)
    other = card(event="same-event", fair=.8, model=.85)
    other["winner_id"] = "p2"
    other["betting"]["selection_id"] = "p2"
    with pytest.raises(ValueError, match="Duplicate canonical event"):
        select_daily_shadow_picks([first, other], PARAMS)


def test_a0_invalid_minimum_rejected():
    from tbt.services.market_only_shadow_research import select_daily_shadow_picks
    for n_min in (0, -1, True, 2.5):
        with pytest.raises(ValueError, match="positive integer"):
            select_daily_shadow_picks([card()], PARAMS, n_min=n_min)
