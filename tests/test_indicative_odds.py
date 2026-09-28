from copy import deepcopy
from pathlib import Path

from tbt.services.indicative_odds import (
    ACE_DF_DISPLAY_MODEL, ESTIMATE_MODEL, annotate_feed_indicative_odds, indicative_price,
)

APP = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")


def test_aces_df_use_stable_illustrative_150_170_and_never_overwrite_real_odds():
    item = {
        "event_id": "1001", "market": "aces", "selection_id": "11",
        "scheduled_at": "2026-09-29T10:00:00Z",
        "projection_confidence": 0.80, "odds": None,
    }
    result = indicative_price(item)
    repeat = indicative_price(dict(item))
    assert result == repeat
    assert 1.50 <= result["indicative_odds"] <= 1.70
    assert result["indicative_odds_method"] == ACE_DF_DISPLAY_MODEL
    assert result["indicative_odds_probability"] is None
    assert result["indicative_odds_scope"] == (
        "display_only_illustrative_150_170_not_bookmaker_not_real_roi"
    )

    df = indicative_price({
        **item, "market": "double_faults", "selection_id": "22",
    })
    assert 1.50 <= df["indicative_odds"] <= 1.70
    assert df["indicative_odds_method"] == ACE_DF_DISPLAY_MODEL
    assert indicative_price({**item, "odds": 1.72}) is None


def test_games_sets_keep_confidence_derived_display_estimate():
    result = indicative_price({
        "market": "games", "projection_confidence": 0.80, "odds": None,
    })
    assert result["indicative_odds"] == 1.18
    assert result["indicative_odds_method"] == ESTIMATE_MODEL
    assert result["indicative_odds_scope"] == "display_only_not_bookmaker_not_real_roi"


def test_missing_or_invalid_confidence_never_invents_price():
    for confidence in (None, 0, 0.3, 1.1, float("nan")):
        assert indicative_price({"market": "games", "projection_confidence": confidence}) is None
    assert indicative_price({"market": "match_winner", "projection_confidence": .8}) is None


def test_all_four_markets_estimated_without_outcome_leakage():
    original = [
        {"market": "aces", "projection_confidence": 0.86,
         "price_status": "projection_only", "odds": None},
        {"market": "double_faults", "projection_confidence": 0.73,
         "price_status": "projection_only", "odds": None},
        {"market": "games", "projection_confidence": 0.66,
         "price_status": "projection_only", "odds": None},
        {"market": "sets", "projection_confidence": 0.81,
         "price_status": "projection_only", "odds": None},
    ]
    stored = deepcopy(original)
    ledger = [{"market_publications": original}]
    feed = {
        "ace_picks": [deepcopy(original[0]), deepcopy(original[1])],
        "sg_picks": [deepcopy(original[2]), deepcopy(original[3])],
        "results": [{"market_publications": deepcopy(original)}],
        "betting_performance": {"overall": {"roi": 0.12}},
    }
    decorated, audit = annotate_feed_indicative_odds(feed)
    assert audit["historic_estimates_total"] == 4
    assert all(v == 1 for v in audit["historic_estimates_by_market"].values())
    assert all(x.get("indicative_odds") for x in decorated["results"][0]["market_publications"])
    assert decorated["betting_performance"]["overall"]["roi"] == .12
    assert ledger[0]["market_publications"] == stored
    assert all(p["odds"] is None for p in decorated["results"][0]["market_publications"])


def test_results_ui_distinguishes_estimates_from_real_prices():
    assert "function stableAceDfIndicativeOdds(row)" in APP
    assert "function projectionIndicativeOdds(row)" in APP
    assert "function indicativeOddsHint()" in APP
    assert "displayedProjectionOdds" in APP
    assert "not a bookmaker quote" in APP
    assert "indicative odds" in APP
    assert "projectionUnits=publication?.result?.profit_units" in APP
