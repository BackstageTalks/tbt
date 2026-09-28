"""Live GAMES/SETS require real prices; ACES/DF may use explicit indicative display odds."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
PIPE = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")


def test_real_quotes_still_require_provider_provenance_and_sg_stays_strict():
    live = APP[APP.index("function authenticLiveProjection("):
               APP.index("function dailyHubRow(")]
    assert "row?.price_status==='priced_projection'" in live
    assert "Number.isFinite(odds)&&odds>=1.50" in live
    assert "Boolean(row?.captured_at)" in live
    assert "key==='sg'?value.filter(authenticLiveProjection):value" in live
    assert "['aces','double_faults'].includes(market)" in live
    assert "const approx=projectionIndicativeOdds(row)" in live
    assert "hubNumberHtml('N/A',reason)" in live


def test_pipeline_keeps_ace_df_projection_only_but_sg_requires_real_price():
    selection = PIPE[PIPE.index("ace_picks, ace_report = select_ace_picks("):
                     PIPE.index("sg_picks, sg_report = select_sg_picks(")]
    assert "available_markets_by_event=None" in selection

    live = PIPE[PIPE.index("# GAMES/SETS stay strict real-price bets."):
                PIPE.index("# Ten per independent category")]
    assert 'row.get("price_status") == "priced_projection"' in live
    assert 'and provider > 0 and bool(row.get("captured_at"))' in live
    assert 'and 1.50 <= odds < float("inf")' in live
    assert "ace_picks = [row for row in ace_picks if publishable_api_price(row)]" not in live
    assert "sg_picks = [row for row in sg_picks if publishable_api_price(row)]" in live
