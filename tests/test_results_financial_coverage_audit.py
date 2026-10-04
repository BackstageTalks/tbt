"""Financial KPI audit: screenshot-equivalent GAMES + DOUBLES samples.

The historical display-only projection odds remain visible in individual
Rows, but cannot create fictional net ROI/Yield. These tests exercise the
same backend helper used by all rolling windows and admin KPI cards.
"""
from copy import deepcopy
from pathlib import Path

from tbt.services.engine import _betting_metrics, betting_performance

ROOT = Path(__file__).resolve().parents[1]


def _p(section, market, selection, odds, correct=True, *, price_status=None, stake=None, profit=None):
    p = {
        "section": section, "market": market,
        "selection_id": selection, "issued_at": "2026-09-25T10:00:00+00:00",
        "odds": odds, "result": {"status": "hit" if correct else "miss", "correct": correct},
    }
    if price_status is not None:
        p["price_status"] = price_status
    if stake is not None:
        p["result"]["staked_units"] = stake
        p["result"]["profit_units"] = profit
    return p


def test_five_winning_games_can_have_only_one_real_quote():
    real = _p("games", "games", "over-19.5", 1.83, price_status="priced_projection", stake=1, profit=.83)
    illustrative = [
        _p("games", "games", "over-19.9", None, price_status="projection_only"),
        _p("games", "games", "over-20.6", None, price_status="projection_only"),
        _p("games", "games", "over-20.6-other", None, price_status="projection_only"),
        _p("games", "games", "over-20.6-last", None, price_status="projection_only"),
    ]
    for row, quote in zip(illustrative, (1.65, 1.67, 1.55, 1.54)):
        row.update(
            historical_display_placeholder_odds=quote,
            historical_display_placeholder_source="synthetic_illustrative_not_bookmaker",
        )
    pubs = illustrative[:2] + [real] + illustrative[2:]
    original = deepcopy(pubs)
    actual = _betting_metrics(pubs)
    # A visible 5-0 with four theoretical per-row "+units" MUST NOT be
    # mislabeled as five actual bookmaker bets (3.24u / 5 = 64.8%).
    assert actual["wins"] == 1
    assert actual["staked_units"] == 1
    assert actual["profit_units"] == .83
    assert actual["roi"] == .83
    assert actual["avg_odds"] == 1.83
    assert pubs == original
    results = [
        {"event_id": f"game-{i}", "market_publications": [p]}
        for i, p in enumerate(pubs)
    ]
    report = betting_performance(results)
    assert report["overall"]["profit_units"] == .83
    assert report["sections"]["games"]["staked_units"] == 1
    assert report["projections"]["games"]["n"] == 5
    assert report["projections"]["games"]["hits"] == 5


def test_doubles_three_actual_quotes_are_profit_1_56u_and_roi_52_percent():
    pubs = [
        _p("doubles", "match_winner", "team-1", 1.40, stake=1, profit=.40),
        _p("doubles", "match_winner", "team-2", 1.80, stake=1, profit=.80),
        _p("doubles", "match_winner", "team-3", 1.36, stake=1, profit=.36),
    ]
    metric = _betting_metrics(pubs)
    assert metric["wins"] == 3 and metric["losses"] == 0
    assert metric["staked_units"] == 3
    assert round(metric["profit_units"], 8) == 1.56
    assert round(metric["roi"] * 100, 8) == 52
    assert round(metric["avg_odds"], 8) == 1.52


def test_hidden_quote_precision_can_explain_one_tenth_percent_difference():
    pubs = [
        _p("doubles", "match_winner", "team-1", 1.401, stake=1, profit=.401),
        _p("doubles", "match_winner", "team-2", 1.801, stake=1, profit=.801),
        _p("doubles", "match_winner", "team-3", 1.361, stake=1, profit=.361),
    ]
    m = _betting_metrics(pubs)
    assert round(m["profit_units"], 2) == 1.56
    assert round(m["roi"] * 100, 1) == 52.1
    # KPI retains exact issued settlement precision; screen rounds individual
    # quotes and units to two decimals. Never silently adjust real ledger.


def test_fake_price_status_cannot_enter_any_aggregate():
    bad = _p("games", "games", "fake", 1.67, price_status="indicative", stake=1, profit=.67)
    bad2 = _p("games", "games", "malformed", "not-an-odd", price_status="priced_projection", stake=1, profit=.6)
    noncontract = _p("games", "games", "wrong-contract", 1.70, price_status="priced", stake=1, profit=.70)
    genuine = _p("games", "games", "real", 1.83, price_status="priced_projection", stake=1, profit=.83)
    m = _betting_metrics([bad, bad2, noncontract, genuine])
    assert m["staked_units"] == 1
    assert m["profit_units"] == .83
    assert m["avg_odds"] == 1.83
    assert m["roi"] == .83


def test_no_extra_public_results_copy_or_layout_changes():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "Jednotky / DATA DEPTH</th>" not in app
    assert "<th>Jednotky</th>" in app
    assert "<small>${escapeHtml(depthText)}</small>" not in app
    assert "const depthText=Number.isFinite(depth)" not in app
    assert "bez Short Odds" not in app[app.index("function resultsSummary()"):app.index("function primeDetailCard(")]
    assert "real settled stakes" in app
    assert "settled profit" in app
    # ACES/DF intentionally use their Results display quote for 1u presentation
    # KPIs, while every other category keeps verified real-settlement accounting.
    assert "const aceDfKpiOdds=aceDfResultKpiOdds(publication)" in app
    assert ":resultVisibleUnits(publication,outcome,resultVisibleOdds(publication));" in app
    assert "const aceDfCategory=!filters?.membership&&(category==='ace'||category==='double_faults')" in app
    assert "Other Results categories retain verified real-stake financial KPIs only." in app
    assert "const units=outcome.kind==='void'?0:rawUnits;" in app
    assert "projectionMarket?status==='priced_projection'" in app
