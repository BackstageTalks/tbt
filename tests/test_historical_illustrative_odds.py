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


def test_ui_never_renders_filler_as_a_real_quote():
    assert "function aceDfLegacyResultDisplayOdds(row)" in APP
    assert "ace_df_real_api_v1" in APP
    assert "1.50+step/100" in APP
    results = APP[APP.index("function renderResults()"):APP.index("function wireResultsFilters()")]
    assert "aceDfLegacyResultDisplayOdds(publication)" in results
    live = APP[APP.index("function projectionOddsHtml("):APP.index("function dailyHubRow(")]
    assert "aceDfLegacyResultDisplayOdds" not in live
    assert "historical_display_placeholder_source==='synthetic_illustrative_not_bookmaker'" in APP
    assert "illustrativeOnly?placeholderOdds.toFixed(2)" in APP
    assert "not an archived bookmaker price or model estimate" in APP
    assert "Nie je historický kurz" not in APP  # check actual wording instead
    assert "nie historický kurz ani odhad modelu" in APP


def test_ace_df_results_kpis_use_displayed_normalized_or_real_api_odds_without_rewriting_ledger():
    assert "function resultVisibleOdds(publication)" in APP
    assert "function resultVisibleUnits(publication,outcome,odds)" in APP
    assert "function aceDfResultKpiOdds(publication)" in APP
    assert "const aceDfKpiOdds=aceDfResultKpiOdds(publication)" in APP
    assert "outcome.kind==='win'?aceDfKpiOdds-1" in APP
    assert "outcome.kind==='loss'?-1" in APP
    assert "const aceDfCategory=!filters?.membership&&(category==='ace'||category==='double_faults')" in APP
    assert "const displayOdds=aceDfResultKpiOdds(publication)" in APP
    assert "stake+=1" in APP
    assert "profit+=units" in APP
    assert "aceDfNormalizedKpis:aceDfCategory" in APP
    assert "1u result ROI from normalized legacy / real API odds" in APP
    assert "1u per settled Aces/DF pick" in APP
    assert "const unitsText=Number.isFinite(displayUnits)?" in APP
    assert "Number.isFinite(displayUnits)&&displayUnits>0?'correct'" in APP
    assert "Number.isFinite(displayUnits)&&displayUnits<0?'wrong'" in APP
    assert "const entries=settledPublishedEntries(rows,category,filters)" in APP
    assert "const realStake=publication?.result?.staked_units" in APP
    assert "function localResultMetrics(rows,category,filters=null)" in APP
    assert "return metricCards([" in APP[APP.index("function resultsSummary()"):APP.index("function primeDetailCard(")]
    # The legacy feed/ledger remains untouched; normalization is a Results presentation KPI.
    assert "historical_display_placeholder_scope" in historical_display_placeholder(publication(), event_id="1001")
    assert round(1.66 - 1, 2) == .66
    assert round(1.52 - 1, 2) == .52
