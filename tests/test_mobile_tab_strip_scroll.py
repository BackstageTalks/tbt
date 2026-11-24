"""Mobile tab-strip contract: hidden last Dvojchyby tab remains reachable."""
from pathlib import Path


def test_mobile_market_tabs_have_visible_horizontal_scroll_and_no_clipping_mask():
    css = Path("web/blinq-unified-skin.css").read_text(encoding="utf-8")
    marker = "/* 2026-11-22: full-width touch-scroll for every daily-market tab on mobile."
    assert marker in css
    rules = css.split(marker, 1)[1]
    assert "#dailyHubTabs.daily-tabs" in rules
    assert "overflow-x:auto!important" in rules
    assert "flex-wrap:nowrap!important" in rules
    assert "scrollbar-width:thin!important" in rules
    assert "mask-image:none!important" in rules
    assert "padding-inline-end:20px!important" in rules
    index = Path("web/index.html").read_text(encoding="utf-8")
    assert "mobile-tabs-scroll=20261122" in index
