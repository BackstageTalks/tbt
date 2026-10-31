"""Desktop-inspired mobile polish: safe cascade, public-only scope and hero.
CSS-only release: never change betting values, entitlement gates or layout of
special markets in JS. The browser gates verify computed appearance.
"""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
CSS = (WEB / "blinq-responsive-polish.css").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_latest_stylesheet_is_last_and_versioned():
    url = "/blinq-responsive-polish.css?v=7360&p=61&mobile-editorial=20261031-1&hero-frame=1"
    assert url in INDEX
    assert INDEX.index("blinq-mobile-unified-cards.css?") < INDEX.index(url)
    assert INDEX.count("blinq-responsive-polish.css?") == 1


def test_hero_frame_does_not_modify_admin_banner_or_artwork():
    hero_css = CSS.split("@media(max-width:600px)", 1)[0]
    assert "body#blinqPremium.blinq-home:not(.blinq-admin) #dashboardHero" in hero_css
    assert "border-radius:14px" in hero_css
    assert "overflow:hidden" in hero_css
    assert "object-position" not in CSS
    assert "object-fit" not in CSS
    assert "hero-copy-x" not in CSS
    assert "hero-img-x" not in CSS


def test_flat_public_mobile_cards_only():
    assert "@media(max-width:600px)" in CSS
    assert "@media(min-width:" not in CSS
    assert "bqm-enabled:not(.blinq-admin)" in CSS
    assert ".hub-pick" in CSS and "border-top:1px solid" in CSS
    assert ".hub-confidence-cell" in CSS and ".hub-odds:nth-child(6)" in CSS
    assert ".results-table tbody tr.results-card-row" in CSS
    assert "#mobileTabs" in CSS
    assert "grid-template-areas" not in CSS
    assert "display:none!important" in CSS  # only duplicate native table-label
    assert "hub-row-locked) .daily-hub-table" not in CSS
    assert "#dashboardKpis" in CSS
