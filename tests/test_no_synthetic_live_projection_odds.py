"""Current public projection bets must be genuine bookmaker-priced offers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
PIPE = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")


def test_live_cards_require_exact_api_odds_and_no_model_fallback():
    live = APP[APP.index("function authenticLiveProjection("):
               APP.index("function dailyHubRow(")]
    assert "row?.price_status==='priced_projection'" in live
    assert "Number.isFinite(odds)&&odds>=1.50" in live
    assert "Boolean(row?.captured_at)" in live
    assert "['ace','sg'].includes(key)?value.filter(authenticLiveProjection)" in live
    assert "const approx=projectionIndicativeOdds(row)" not in live
    assert "hubNumberHtml('N/A',reason)" in live


def test_actual_api_price_requirement_is_enforced_before_issuing_bets():
    live = PIPE[PIPE.index("# Market-first publication is strict:"):
                PIPE.index("# Ten per independent category")]
    assert 'row.get("price_status") == "priced_projection"' in live
    assert 'and provider > 0 and bool(row.get("captured_at"))' in live
    assert 'and 1.50 <= odds < float("inf")' in live
    assert "ace_picks = [row for row in ace_picks if publishable_api_price(row)]" in live
    assert "sg_picks = [row for row in sg_picks if publishable_api_price(row)]" in live
