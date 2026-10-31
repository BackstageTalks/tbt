"""Historical fillers must NEVER masquerade as archived bookmaker quotes."""
from copy import deepcopy
from pathlib import Path

from tbt.services.indicative_odds import (
    annotate_feed_indicative_odds,
    historical_display_placeholder,
)

APP = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")


def publication(*, odds=None, market="games", result="hit", issued=True):
    return {
        "market": market,
        "selection": "Over 23.5 Games",
        "selection_id": "games:over:23.5",
        "publication_key": "event:1001:games:over:23.5",
        "issued_at": "2026-09-20T10:00:00Z" if issued else None,
        "odds": odds,
        "price_status": "priced_projection" if odds else "projection_only",
        "result": {"status": result, "profit_units": None, "staked_units": 0},
        "projection_confidence": 0.82,
    }


def test_stable_range_only_on_genuine_missing_issued_projection_quotes():
    missing = publication()
    one = historical_display_placeholder(missing, event_id="1001")
    two = historical_display_placeholder(missing, event_id="1001")
    assert one == two
    assert 1.50 <= one["historical_display_placeholder_odds"] <= 1.70
    assert one["historical_display_placeholder_source"] == "synthetic_illustrative_not_bookmaker"
    assert historical_display_placeholder(publication(odds=1.86), event_id="1001") is None
    assert historical_display_placeholder(publication(issued=False), event_id="1001") is None
    assert historical_display_placeholder(publication(market="match_winner"), event_id="1001") is None
    # Win/loss is deliberately absent from the identity and must not influence the number.
    loss = publication(result="miss")
    assert historical_display_placeholder(loss, event_id="1001") == one


def test_illustrative_feed_backfill_does_not_change_original_ledger_or_result():
    p = publication()
    priced = publication(odds=1.86, market="sets")
    priced["result"] = {"status": "miss", "profit_units": -1.0, "staked_units": 1.0}
    ledger = [{"event_id": "1001", "market_publications": [deepcopy(p), deepcopy(priced)]}]
    original = deepcopy(ledger)
    feed = {
        "results": [{"event_id": "1001", "market_publications": [deepcopy(p), deepcopy(priced)]}],
        "betting_performance": {"overall": {"roi": -0.12}},
    }
    decorated, audit = annotate_feed_indicative_odds(feed)
    result = decorated["results"][0]["market_publications"]
    assert audit["historical_illustrative_only_total"] == 1
    assert result[0]["odds"] is None
    assert result[0]["price_status"] == "projection_only"
    assert result[0]["result"] == p["result"]
    assert result[0]["historical_display_placeholder_source"] == "synthetic_illustrative_not_bookmaker"
    assert "indicative_odds" not in result[0]
    assert result[1]["odds"] == 1.86
    assert "historical_display_placeholder_odds" not in result[1]
    assert result[1]["result"] == priced["result"]
    assert decorated["betting_performance"]["overall"]["roi"] == -0.12
    assert ledger == original


def test_ui_refuses_historical_filler_as_quote_or_units():
    assert "function verifiedProjectionOdds(row)" in APP
    assert "function aceDfLegacyResultDisplayOdds(row)" not in APP
    assert "1.50+step/100" not in APP
    assert "historical_display_placeholder_odds" not in APP
    results = APP[APP.index("function renderResults()"):APP.index("function wireResultsFilters()")]
    assert "const realProjectionOdds=verifiedProjectionOdds(publication)" in results
    assert "const displayedProjectionOdds=Number.isFinite(realProjectionOdds)?realProjectionOdds.toFixed(2):'—';" in results
    assert "const displayUnits=resultVisibleUnits(publication,outcome,realProjectionOdds)" in results
    assert "projectionIndicativeOdds(publication)" not in results
    assert "aceDfLegacyResultDisplayOdds(publication)" not in results


def test_results_kpis_require_a_verified_market_and_a_settled_real_stake():
    assert "function resultVisibleOdds(publication)" in APP
    assert "return verifiedProjectionOdds(publication);" in APP
    assert "function resultVisibleUnits(publication,outcome,odds)" in APP
    assert "if(!Number.isFinite(odds)||odds<1.50)return NaN;" in APP
    assert "function aceDfResultKpiOdds(publication)" in APP
    assert "return ['aces','double_faults'].includes(market)?verifiedProjectionOdds(publication):NaN;" in APP
    assert "const displayOdds=aceDfResultKpiOdds(publication)" in APP
    assert "if(!Number.isFinite(displayOdds)||!Number.isFinite(realStake)||realStake<=0||!Number.isFinite(realProfit))continue;" in APP
    assert "profit+=realProfit;" in APP
    assert "stake+=1;" in APP
    assert "const actualOdds=projectionMarket?verifiedProjectionOdds(publication)" in APP
    assert "verified settled profit only" in APP
    assert "1u result ROI from normalized legacy / real API odds" not in APP
    assert "outcome.kind==='win'?aceDfKpiOdds-1" not in APP
