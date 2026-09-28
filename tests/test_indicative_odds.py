from copy import deepcopy
from pathlib import Path

from tbt.services.indicative_odds import (
    ESTIMATE_MODEL, annotate_feed_indicative_odds, indicative_price,
)

APP = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")


def test_frozen_confidence_approximates_never_overwrites_real_odds():
    item = {"market": "aces", "projection_confidence": 0.80, "odds": None}
    result = indicative_price(item)
    assert result["indicative_odds"] == 1.18
    assert result["indicative_odds_method"] == ESTIMATE_MODEL
    assert result["indicative_odds_scope"] == "display_only_not_bookmaker_not_real_roi"
    assert indicative_price({**item, "odds": 1.72}) is None


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
    assert "function projectionIndicativeOdds(row)" in APP
    assert "function indicativeOddsHint()" in APP
    assert "displayedProjectionOdds" in APP
    assert "not a bookmaker quote" in APP
    assert "projectionUnits=publication?.result?.profit_units" in APP
