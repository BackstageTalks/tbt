"""Keep public hero rounding presentation-only, on desktop and mobile."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"

def test_hero_frame_stylesheet_loaded_after_mobile_layouts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/blinq-hero-frame.css?v=7360&p=61&frame=20261031-1" in html
    assert html.index("/blinq-mobile-unified-cards.css?") < html.index("/blinq-hero-frame.css?")

def test_hero_frame_is_public_and_does_not_override_managed_content():
    css = (WEB / "blinq-hero-frame.css").read_text(encoding="utf-8")
    assert 'body#blinqPremium.blinq-home:not(.blinq-admin) #dashboardHero' in css
    assert 'body#blinqPremium.blinq-home.bqm-enabled:not(.blinq-admin) #dashboardHero' in css
    assert 'border-radius: 16px' in css
    assert 'border-radius: 11px' in css
    assert 'overflow: hidden' in css
    for forbidden in ('height:', 'width:', 'object-position', 'dashboard-hero-copy', 'hero-slide-image', 'mobileTabs', 'site-header', 'site-footer', 'dashboardKpis'):
        assert forbidden not in css
