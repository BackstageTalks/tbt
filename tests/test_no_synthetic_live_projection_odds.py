"""Live SG bets require genuine quotes; ACES/DF may show display-only indicative odds."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
PIPE = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")


def test_games_sets_still_require_exact_api_odds_but_aces_df_allow_indicative_display():
    live = APP[APP.index("function authenticLiveProjection("):
               APP.index("function dailyHubRow(")]
    assert "row?.price_status==='priced_projection'" in live
    assert "Number.isFinite(odds)&&odds>=1.50" in live
    assert "Boolean(row?.captured_at)" in live
    assert "function displayableAceProjection(row)" in live
    assert "key==='ace'?value.filter(displayableAceProjection)" in live
    assert "key==='sg'?value.filter(authenticLiveProjection)" in live
    assert "indicative>=1.50&&indicative<=1.70" in live
    assert "hubNumberHtml(indicative.toFixed(2)" in live
    assert "hubNumberHtml('N/A',reason)" in live


def test_pipeline_keeps_unpriced_aces_df_only_as_non_bookmaker_projection_cards():
    live = PIPE[PIPE.index("# Real bookmaker quotes remain strict."):
                PIPE.index("# Ten per independent category")]
    assert 'row.get("price_status") == "priced_projection"' in live
    assert 'and provider > 0 and bool(row.get("captured_at"))' in live
    assert 'and 1.50 <= odds < float("inf")' in live
    assert 'market in {"aces", "double_faults"}' in live
    assert 'row.get("price_status") == "projection_only"' in live
    assert 'row.get("odds") in (None, "")' in live
    assert "publishable_api_price(row) or publishable_ace_projection(row)" in live
    assert "sg_picks = [row for row in sg_picks if publishable_api_price(row)]" in live


def test_aces_df_selection_is_not_blocked_by_bookmaker_market_availability():
    selector = PIPE[PIPE.index("ace_picks, ace_report = select_ace_picks("):
                    PIPE.index("sg_picks, sg_report = select_sg_picks(")]
    assert "available_markets_by_event=None" in selector
