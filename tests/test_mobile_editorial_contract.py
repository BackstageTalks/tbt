"""BlinQ editorial mobile feed — safe scoping and asset-order checks."""

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_editorial_layer_is_loaded_last():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    visual = index.index("/blinq-mobile-visual.css?")
    density = index.index("/blinq-mobile-density.css?")
    unified = index.index("/blinq-mobile-unified-cards.css?")
    editorial = index.index("/blinq-mobile-editorial.css?v=7360&p=61&editorial=20261031-1")
    assert visual < density < unified < editorial


def test_editorial_layer_is_phone_only_and_public_only():
    css = (WEB / "blinq-mobile-editorial.css").read_text(encoding="utf-8")
    assert "@media (max-width: 600px)" in css
    assert "@media (min-width:" not in css
    assert css.count("body#blinqPremium") == css.count(":not(.blinq-admin)")
    assert "#mobileTabs" not in css
    assert ".site-header" not in css
    assert ".site-footer" not in css
    assert "#dashboardKpis" not in css
    assert "hub-row-locked) {" not in css
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
