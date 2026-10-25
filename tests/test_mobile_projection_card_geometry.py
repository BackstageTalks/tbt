"""Contracts for readable BlinQ prediction cards across mobile market tabs."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mobile_card_css_loaded_after_existing_styles():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "/blinq-daily-hub-mobile.css?v=7360&daily-mobile=20261025-1" in html
    assert html.index("/blinq-mobile.css") < html.index("/blinq-daily-hub-mobile.css")
    assert html.index("/blinq-detail.css") < html.index("/blinq-daily-hub-mobile.css")


def test_projection_fields_do_not_share_css_grid_area():
    css = (ROOT / "web/blinq-daily-hub-mobile.css").read_text(encoding="utf-8")
    assert "@media (max-width:900px)" in css
    assert 'grid-template-areas:"tournament time" "match match" "pick pick" "projection odds" "confidence action"' in css
    for tab in ("ace", "double_faults", "games", "sets"):
        assert f'[data-tab="{tab}"]' in css
    assert "grid-area:projection!important" in css
    assert "grid-area:odds!important" in css
    assert "grid-area:confidence!important" in css
    assert "min-height:0!important" in css
    assert "overflow-wrap:break-word!important" in css
    assert "white-space:normal!important" in css


def test_rendered_market_column_order_matches_css_contract():
    js = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert '<td class="hub-rank">' in js
    assert '<td class="hub-time">' in js
    assert '<td class="hub-tournament-cell">' in js
    assert '<td class="hub-match-cell">' in js
    assert 'sourceTab===\'ace\'||sourceTab===\'double_faults\'' in js
    assert '<td class="hub-pick">' in js
    assert '<td class="hub-odds hub-number-cell">' in js
    assert '<td class="hub-confidence-cell">' in js
    assert 'data-hub-market=' in js


def test_table_desktop_and_locked_rows_untouched():
    css = (ROOT / "web/blinq-daily-hub-mobile.css").read_text(encoding="utf-8")
    assert ":not(.hub-row-locked)" in css
    assert "@media (min-width:901px)" not in css
    assert "display:none!important" in css  # only rank is hidden, not content
