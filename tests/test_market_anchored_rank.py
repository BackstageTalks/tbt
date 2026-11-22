"""Flag-gated market-anchored ranking and separately gated TOP floor.

No flag may modify champion behaviour, existing public probability, odds,
eligibility floors, category assignment, or any existing model parameters.
"""
import copy
import math
from pathlib import Path

import pytest

from test_market_selection import row
from tbt.services import market_anchored_rank as mar
from tbt.services.market_selection import select_market_sections


def _logit(x):
    return math.log(x / (1 - x))


def _sig(z):
    return 1 / (1 + math.exp(-z))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(mar.ENV_RANK, raising=False)
    monkeypatch.delenv(mar.ENV_FILL, raising=False)
    monkeypatch.delenv(mar.ENV_TOP_SIDE, raising=False)


def _slate():
    return [row('a', .70, 1.60, 2.40),
            row('b', .66, 1.52, 2.60, depth=1.0),
            row('c', .58, 1.70, 2.20)]


def _ids(result, key='top_daily_picks'):
    return [c['event_id'] for c in result[key]]


def test_rank_defaults_to_champion_and_invalid_values_fail_safe(monkeypatch):
    assert mar.rank_mode() == "model"
    for value in ("", "MARKET", "true", "1", "invalid"):
        monkeypatch.setenv(mar.ENV_RANK, value)
        assert mar.rank_mode() == "model"
    monkeypatch.setenv(mar.ENV_RANK, "market_anchored")
    assert mar.rank_mode() == "market_anchored"
    monkeypatch.setenv(mar.ENV_RANK, "  Market_Anchored ")
    assert mar.rank_mode() == "market_anchored"


def test_flags_off_output_identical_with_no_new_fields(monkeypatch):
    baseline = select_market_sections(copy.deepcopy(_slate()), top_limit=3)
    for source in ("model", "junk"):
        monkeypatch.setenv(mar.ENV_RANK, source)
        assert select_market_sections(copy.deepcopy(_slate()), top_limit=3) == baseline
    for section in ("top_daily_picks", "prime_picks", "value_picks"):
        for card in baseline[section]:
            assert "rank_probability" not in card
            assert "rank_source" not in card


def test_flag_on_only_reorders_eligible_top_and_preserves_model_p(monkeypatch):
    off = select_market_sections(copy.deepcopy(_slate()), top_limit=1)
    assert _ids(off) == ["a"]
    off_full = select_market_sections(copy.deepcopy(_slate()), top_limit=3)
    monkeypatch.setenv(mar.ENV_RANK, "market_anchored")
    on = select_market_sections(copy.deepcopy(_slate()), top_limit=1)
    assert _ids(on) == ["b"]
    on_full = select_market_sections(copy.deepcopy(_slate()), top_limit=3)
    baseline = {c["event_id"]: c["probability"] for c in off_full["top_daily_picks"]}
    modified = {c["event_id"]: c["probability"] for c in on_full["top_daily_picks"]}
    assert baseline == modified and set(baseline) == set(modified)


def test_rank_probability_formula():
    card = {"probability": .70, "scheduled_at": "2026-09-07T12:00:00Z",
            "betting": {"captured_at": "2026-09-07T07:00:00Z",
                        "fair_implied_probability": .60}}
    val, source = mar.compute_rank_probability(card)
    q = _sig(1.102 * _logit(.60) - .009)
    assert source == "market_anchored"
    assert val == pytest.approx(_sig(.8*_logit(q)+.2*_logit(.70)), abs=1e-12)


@pytest.mark.parametrize("captured", ["2026-09-07T12:00:00Z",
                                     "2026-09-07T13:00:00Z", None, "bad"])
def test_no_prestart_quote_means_pure_model_fallback(captured):
    card = {"probability": .70, "scheduled_at": "2026-09-07T12:00:00Z",
            "betting": {"captured_at": captured, "fair_implied_probability": .60}}
    assert mar.compute_rank_probability(card) == (.70, "model_fallback")


def test_invalid_fair_means_pure_model_fallback():
    for fair in (None, 0, 1, 1.2, float("nan"), "x"):
        card = {"probability": .70, "scheduled_at": "2026-09-07T12:00:00Z",
                "betting": {"captured_at": "2026-09-07T07:00:00Z",
                            "fair_implied_probability": fair}}
        assert mar.compute_rank_probability(card) == (.70, "model_fallback")


def test_false_or_invalid_rank_field_does_not_pollute_champion():
    assert mar.rank_value({"probability": .66, "rank_probability": .99}) == .66


def test_emergency_fill_off_by_default():
    result = select_market_sections([row("c", .58, 1.70, 2.20)], top_limit=3)
    assert _ids(result) == []


def test_emergency_fill_requires_flag_and_market_agreement(monkeypatch):
    monkeypatch.setenv(mar.ENV_FILL, "true")
    choices = [row("a", .70, 1.60, 2.40),
               row("c", .58, 1.70, 2.20),
               row("d", .56, 1.80, 2.10)]
    res = select_market_sections(copy.deepcopy(choices), top_limit=3)
    assert _ids(res)[0] == "a" and len(_ids(res)) == 3
    tiers = {c["event_id"]: c["selection_tier"] for c in res["top_daily_picks"]}
    assert tiers["a"] == "sports_0.65"
    assert tiers["c"] == "emergency_fill" and tiers["d"] == "emergency_fill"


def test_emergency_fill_never_adds_opposite_market_favorite(monkeypatch):
    monkeypatch.setenv(mar.ENV_FILL, "true")
    res = select_market_sections([row("w", .58, 2.60, 1.52)], top_limit=3)
    assert "w" not in _ids(res)


def test_emergency_fill_never_duplicates_or_exceeds_minimum(monkeypatch):
    monkeypatch.setenv(mar.ENV_FILL, "true")
    choices = [row("a", .70, 1.60, 2.40),
               row("b", .66, 1.52, 2.60),
               row("e", .72, 1.65, 2.30),
               row("c", .58, 1.70, 2.20)]
    res = select_market_sections(copy.deepcopy(choices), top_limit=10)
    ids = _ids(res)
    assert len(ids) == len(set(ids))
    assert "c" not in ids


def test_workflow_both_features_fail_closed_without_independent_owner_approval():
    lines = Path(".github/workflows/data.yml").read_text(encoding="utf-8").splitlines()
    rank = [x for x in lines if x.strip().startswith("TBT_RANK_SOURCE:")]
    fill = [x for x in lines if x.strip().startswith("TBT_TOP_EMERGENCY_FILL:")]
    assert len(rank) == len(fill) == 1
    assert "vars.TBT_MARKET_ANCHORED_OWNER_APPROVED == 'true'" in rank[0]
    assert "vars.TBT_RANK_SOURCE == 'market_anchored'" in rank[0]
    assert "|| 'model'" in rank[0]
    assert "vars.TBT_TOP_EMERGENCY_FILL_OWNER_APPROVED == 'true'" in fill[0]
    assert "vars.TBT_TOP_EMERGENCY_FILL == 'true'" in fill[0]
    assert "|| 'false'" in fill[0]

def test_market_side_gate_defaults_off_even_when_rank_enabled(monkeypatch):
    pool = [row("u", .72, 2.60, 1.52), row("f", .70, 1.60, 2.40)]
    base = select_market_sections(copy.deepcopy(pool), top_limit=3)
    assert "u" in _ids(base)
    assert mar.top_market_side_violation(base["top_daily_picks"][0]) is False
    monkeypatch.setenv(mar.ENV_RANK, "market_anchored")
    assert mar.top_require_market_side_enabled() is False


def test_market_side_flag_only_vetoes_top_market_underdog(monkeypatch):
    pool = [row("u", .72, 2.60, 1.52), row("f", .70, 1.60, 2.40)]
    off = select_market_sections(copy.deepcopy(pool), top_limit=3)
    monkeypatch.setenv(mar.ENV_TOP_SIDE, "1")
    on = select_market_sections(copy.deepcopy(pool), top_limit=3)
    assert "u" in _ids(off)
    assert _ids(on) == ["f"]
    assert on["market_selection"]["top_rejection_counts"][
        mar.TOP_REJECT_REASON] == 1
    for section in ("prime_picks", "value_picks"):
        assert on[section] == off[section]


def test_market_side_no_valid_prestart_evidence_never_vetoes(monkeypatch):
    monkeypatch.setenv(mar.ENV_TOP_SIDE, "1")
    case = row("u", .72, 2.60, 1.52)
    assert mar.top_market_side_violation(case) is True
    case["betting"]["captured_at"] = case["scheduled_at"]
    assert mar.top_market_side_violation(case) is False
    case["betting"]["captured_at"] = "2026-09-07T13:00:00Z"
    assert mar.top_market_side_violation(case) is False
    case["betting"]["captured_at"] = None
    assert mar.top_market_side_violation(case) is False
    case["betting"]["fair_implied_probability"] = None
    assert mar.top_market_side_violation(case) is False


def test_market_side_fair_boundary_and_toggle_handling(monkeypatch):
    import pytest
    monkeypatch.setenv(mar.ENV_TOP_SIDE, "yes")
    c = row("u", .72, 2.60, 1.52)
    c["betting"]["fair_implied_probability"] = .5
    assert not mar.top_market_side_violation(c)
    c["betting"]["fair_implied_probability"] = .49999
    assert mar.top_market_side_violation(c)
    monkeypatch.setenv(mar.ENV_TOP_SIDE, "false")
    assert not mar.top_market_side_violation(c)


def test_market_side_veto_not_bypassed_by_emergency_top_fill(monkeypatch):
    monkeypatch.setenv(mar.ENV_TOP_SIDE, "true")
    monkeypatch.setenv(mar.ENV_FILL, "true")
    pool = [row("u", .72, 2.60, 1.52), row("f", .70, 1.60, 2.40),
            row("small", .58, 1.70, 2.20)]
    on = select_market_sections(copy.deepcopy(pool), top_limit=3)
    assert "u" not in _ids(on)
    assert len(_ids(on)) <= 3
    assert len(_ids(on)) == len(set(_ids(on)))


def test_market_side_workflow_requires_separate_owner_approval():
    lines = Path(".github/workflows/data.yml").read_text(encoding="utf-8").splitlines()
    side = [s for s in lines if s.strip().startswith("TBT_TOP_REQUIRE_MARKET_SIDE:")]
    assert len(side) == 1
    assert "vars.TBT_TOP_REQUIRE_MARKET_SIDE_OWNER_APPROVED == 'true'" in side[0]
    assert "vars.TBT_TOP_REQUIRE_MARKET_SIDE == '1'" in side[0]
    assert "|| 'false'" in side[0]
