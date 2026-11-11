"""Startup perf regression: one full-document translation per initial dashboard render.

Standalone section refreshes still translate immediately. Loader media/CSS are unchanged.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _function_line(name):
    matches = [
        line.strip() for line in APP.splitlines()
        if line.strip().startswith(f"function {name}(")
    ]
    assert len(matches) == 1, name
    return matches[0]


def test_initial_dashboard_runs_only_one_global_translation_pass():
    render = _function_line("renderAllUiContent")
    assert render.count("renderMarketSections(false);") == 1
    assert render.count("translatePublicDom(document.body);") == 1
    assert render.index("renderMarketSections(false);") < render.index(
        "translatePublicDom(document.body);"
    )
    assert render.index("renderSystemFooterStatus();") < render.index(
        "translatePublicDom(document.body);"
    )


def test_standalone_market_refresh_still_translates_and_preserves_all_categories():
    market = _function_line("renderMarketSections")
    assert market.startswith("function renderMarketSections(translateAfter=true){")
    assert market.count("renderMarketSection(") == 5
    for category in ("top_daily", "value", "doubles", "ace", "sg"):
        assert f"renderMarketSection('{category}'" in market
    assert market.endswith("if(translateAfter)translatePublicDom(document.body);}")
    # Other handlers still call with no args: default retains old behavior.
    assert "renderMarketSections();" in APP


def test_loader_artwork_and_background_are_untouched():
    assert 'id="bootSplash"' in HTML
    assert '/assets/blinq-loader.webp' in HTML
    assert '/assets/blinq-loader.gif' in HTML
    assert 'class="boot-splash boot-splash-tennis"' in HTML
