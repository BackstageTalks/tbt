"""BlinQ editorial mobile feed — safe scoping and asset-order checks."""

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_editorial_layer_is_loaded_last():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    visual = index.index("/blinq-mobile-visual.css?")
    density = index.index("/blinq-mobile-density.css?")
    unified = index.index("/blinq-mobile-unified-cards.css?")
    editorial = index.index("/blinq-mobile-editorial.css?v=7360&p=61&editorial=20261031-1")
    hero = index.index("/blinq-hero-frame.css?v=7360&p=61&frame=20261031-1")
    assert visual < density < unified < editorial < hero


def test_editorial_layer_is_phone_only_and_public_only():
    css = (WEB / "blinq-mobile-editorial.css").read_text(encoding="utf-8")
    assert "@media (max-width: 600px)" in css
    assert "@media (min-width:" not in css
    assert css.count("body#blinqPremium") == css.count(":not(.blinq-admin)")
    assert "#mobileTabs" not in css
    assert ".site-header" not in css
    assert ".site-footer" not in css
    assert "#dashboardKpis" not in css
    assert "tbody tr.hub-row-locked {" not in css
    assert "data-tab=\"see_all\"" in css
    assert "min-height: 44px" in css
    assert "#dailyHub" in css and ".results-card-row" in css


def test_prediction_card_uses_one_surface_and_preserves_projection():
    css = (WEB / "blinq-mobile-editorial.css").read_text(encoding="utf-8")
    assert '"tournament time" "match match" "pick action" "confidence number"' in css
    assert '"projection projection"' in css
    assert ".hub-pick-stack small::before" in css
    assert "content: none !important" in css
    assert ".hub-detail:not(.is-locked)" in css
    assert ".hub-odds:nth-child(6)" in css


def test_banner_frame_is_shared_but_no_copy_or_height_overrides():
    css = (WEB / "blinq-hero-frame.css").read_text(encoding="utf-8")
    assert "body#blinqPremium.blinq-home:not(.blinq-admin) #dashboardHero" in css
    assert "body#blinqPremium.blinq-home.bqm-enabled:not(.blinq-admin) #dashboardHero" in css
    assert "border-radius: 16px" in css and "border-radius: 11px" in css
    assert "overflow: hidden" in css
    assert "height:" not in css
    assert "hero-slide-image" not in css
    assert "dashboard-hero-copy" not in css
