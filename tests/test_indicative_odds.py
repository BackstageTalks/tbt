from copy import deepcopy
from pathlib import Path

from tbt.services.indicative_odds import (
    ESTIMATE_MODEL, annotate_feed_indicative_odds, indicative_price,
)

APP = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")


def test_old_confidence_pricing_is_disabled_for_every_projection_market():
    for market in ("aces", "double_faults", "games", "sets"):
        assert indicative_price({
            "market": market, "projection_confidence": .95, "odds": None,
        }) is None
    assert indicative_price({
        "market": "games", "projection_confidence": .8, "odds": 1.86,
    }) is None
    assert "disabled" in ESTIMATE_MODEL


def test_stale_estimates_are_stripped_from_serving_feed_not_ledger():
    original = [
        {"market": market, "projection_confidence": .83,
         "price_status": "projection_only", "odds": None,
         "indicative_odds": 1.15,
         "indicative_odds_method": "frozen_projection_confidence_v1"}
        for market in ("aces", "double_faults", "games", "sets")
    ]
    ledger = [{"market_publications": deepcopy(original)}]
    frozen_ledger = deepcopy(ledger)
    feed = {
        "ace_picks": deepcopy(original[:2]),
        "sg_picks": deepcopy(original[2:]),
        "results": [{"market_publications": deepcopy(original)}],
        "betting_performance": {"overall": {"roi": .12}},
    }
    decorated, audit = annotate_feed_indicative_odds(feed)
    assert audit["historic_estimates_total"] == 0
    assert sum(audit["legacy_estimates_removed_from_feed"].values()) == 8
    assert all("indicative_odds" not in row for row in decorated["sg_picks"])
    assert all("indicative_odds" not in row for row in decorated["results"][0]["market_publications"])
    assert decorated["betting_performance"]["overall"]["roi"] == .12
    assert ledger == frozen_ledger


def test_frontend_never_converts_confidence_or_model_baseline_into_bet():
    assert "function projectionIndicativeOdds(row)" in APP
    assert "return NaN;" in APP[APP.index("function projectionIndicativeOdds(row)"):
                                APP.index("function indicativeOddsHint()")]
    assert "row?.price_status!=='priced_projection'" in APP
    assert "if(sourceTab==='games')" in APP
    assert "No verified odds" in APP
    assert "displayedProjectionOdds" in APP
    assert "projectionUnits=publication?.result?.profit_units" in APP
