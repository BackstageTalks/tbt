"""Approved local ACES are equal-weight 1u Results prices from 1 November onward.

Synthetic regression against known frozen 2 November event/selection identifiers.
Never change the archived publication or infer an old illustrative price.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from tbt.services.dashboard_kpis import local_ace_financial_odds, published_results_metrics
from tbt.services.engine import betting_performance

ROOT = Path(__file__).resolve().parents[1]
DAY = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
ACE_CASES = [
    ("17468525", "289146", 12.5, 1.75),
    ("17449526", "158896", 10.5, 1.80),
    ("17456687", "372310", 6.5, 1.60),
    ("17467964", "270414", 4.5, 1.79),
    ("17457727", "341853", 7.5, 1.72),
]


def ace(event, selection, line, correct=True, *, issued="2026-11-02T09:00:00Z"):
    return {
        "event_id": event,
        "scheduled_at": "2026-11-02T19:00:00Z",
        "market_publications": [{
            "market": "aces", "section": "ace", "selection_id": selection,
            "price_contract": "player_total_ou", "ou_side": "over",
            "market_line": line, "issued_at": issued,
            "price_status": "projection_only", "odds": None,
            "publication_key": f"local-aces-ou-v1:{event}:{selection}:over:{line}",
            "result": {"status": "hit" if correct else "miss", "correct": correct},
        }],
    }


def winner(event, odds, correct):
    return {
        "event_id": event, "scheduled_at": "2026-11-02T15:00:00Z",
        "market_publications": [{
            "market": "match_winner", "section": "top_daily",
            "selection_id": "player-" + event, "issued_at": "2026-11-02T08:00:00Z",
            "price_status": "priced", "odds": odds,
            "result": {"status": "hit" if correct else "miss",
                       "correct": correct, "staked_units": 1.0,
                       "profit_units": odds - 1 if correct else -1.0},
        }],
    }


def test_frozen_2nov_local_prices_match_exact_approved_cents():
    for event, selection, line, expected in ACE_CASES:
        row = ace(event, selection, line)
        assert local_ace_financial_odds(row, row["market_publications"][0]) == expected


def test_elite_every_settled_local_ace_contributes_equally_to_combined_roi():
    # Four standard Results bets have the screenshot's +1.13u / 4u.
    rows = [
        winner("winner-1", 1.98, True), winner("winner-2", 1.58, True),
        winner("winner-3", 1.57, True), winner("winner-4", 1.79, False),
    ]
    assert abs(sum(r["market_publications"][0]["result"]["profit_units"] for r in rows) - 1.13) < 1e-9
    # Add five settled local Aces: 4 wins, 1 loss. They must not disappear
    # when ELITE/ALL rather than the ACES-only filter is selected.
    rows.extend(ace(e, s, line, i != 4) for i, (e, s, line, _) in enumerate(ACE_CASES))
    original = deepcopy(rows)
    financial = published_results_metrics({"results": rows}, "all", now=DAY)
    ledger = betting_performance(rows)["overall"]
    expected_profit = 1.13 + .75 + .80 + .60 + .79 - 1.0
    assert financial["wins"] == ledger["wins"] == 7
    assert financial["losses"] == ledger["losses"] == 2
    assert financial["stake_count"] == 9
    assert financial["staked_units"] == ledger["staked_units"] == 9.0
    assert abs(financial["profit_units"] - expected_profit) < 1e-9
    assert abs(ledger["profit_units"] - expected_profit) < 1e-9
    assert abs(financial["roi"] - expected_profit / 9.0) < 1e-9
    assert rows == original


def test_historical_local_aces_since_nov1_recalculate_in_all_windows():
    recent = ace("17467964", "270414", 4.5, True)
    old = ace("17468525", "289146", 12.5, True, issued="2026-10-30T09:00:00Z")
    old["scheduled_at"] = "2026-10-30T19:00:00Z"
    assert local_ace_financial_odds(old, old["market_publications"][0]) is None
    rows = {"results": [recent, old]}
    all_time = published_results_metrics(rows, "all", now=DAY)
    seven_days = published_results_metrics(rows, "7", now=DAY)
    assert all_time["stake_count"] == seven_days["stake_count"] == 1
    assert abs(all_time["profit_units"] - 0.79) < 1e-9
    assert abs(seven_days["roi"] - .79) < 1e-9


def test_no_local_roi_for_non_ou_or_missing_identity_or_bad_line():
    row = ace("17449526", "158896", 10.5)
    p = row["market_publications"][0]
    for field, invalid in (("price_contract", "player_superiority"),
                           ("ou_side", "middle"), ("selection_id", ""),
                           ("market_line", None)):
        altered = dict(p, **{field: invalid})
        assert local_ace_financial_odds(row, altered) is None
    assert local_ace_financial_odds(row, p) == 1.80


def test_frontend_matches_backend_for_filters_and_monthly_history():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    metrics = app[app.index("function localResultMetrics("):app.index("function resultLiveMaxOddsHtml(")]
    month = app[app.index("function monthlyFinancialRecord("):app.index("function renderMonthlyPerformance(")]
    assert "const localAceOdds=localAceFinancialOdds(publication);" in metrics
    assert "if(Number.isFinite(localAceOdds))" in metrics
    assert "stake+=1;unitSample++" in metrics
    assert "profit+=outcome.kind==='win'?localAceOdds-1:-1;" in metrics
    assert "const localOdds=localAceFinancialOdds(publication);" in month
    assert "return {profit:outcome==='win'?localOdds-1:-1,stake:1,priced:true,odds:localOdds}" in month
    summary = app[app.index("function resultsSummary()"):app.index("function primeDetailCard(")]
    assert "1u na každý vyhodnotený tip s platným kurzom" in summary
