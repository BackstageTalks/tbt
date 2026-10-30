"""Mobile density override: scoping and load-order regression guards."""

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_density_css_loaded_after_mobile_visual():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/blinq-mobile-density.css?v=7360&p=61&density=20261030-2" in index
    assert index.index("/blinq-mobile-visual.css?") < index.index("/blinq-mobile-density.css?")


def test_density_is_phone_only_and_public_only():
    css = (WEB / "blinq-mobile-density.css").read_text(encoding="utf-8")
    assert "@media (max-width: 600px)" in css
    assert "@media (max-width: 360px)" in css
    assert "@media (min-width:" not in css
    assert css.count("body#blinqPremium") == css.count(":not(.blinq-admin)")
    assert "bqm-enabled:not(.blinq-admin)" in css
    assert "tbody tr.hub-row-locked {" not in css
    assert "grid-template-areas" in css
    assert "#dailyHub:is([data-tab=\"daily\"],[data-tab=\"value\"])" in css
    assert "display: none" not in css
    assert ".hub-pick-stack small::before" in css
    assert "PREDIKCIA · " in css
    assert "td.hub-pick::before" in css


def test_touch_targets_and_managed_banner_preserved():
    css = (WEB / "blinq-mobile-density.css").read_text(encoding="utf-8")
    assert "min-height: 44px" not in css
    assert "#dashboardHero" not in css
    assert "#mobileTabs" not in css
