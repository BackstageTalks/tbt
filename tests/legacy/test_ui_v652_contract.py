from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v652_footer_and_model_location_contract():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "This data is provided for informational and analytical purposes only. Powered by BackstageTalks Statistical Engine." in html
    assert 'id="footerModelState"' in html
    assert 'id="sidebarModelState"' not in html
    assert "footerModelState" in js
    assert "sidebarModelState" not in js


def test_v652_compact_membership_and_avatar_tooltip_contract():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'id="accountHoverTooltip"' in html
    assert 'id="tooltipAccountEmail"' in html
    assert 'id="tooltipAccountPlan"' in html
    assert 'id="tooltipAccountRemaining"' in html
    assert "account-membership-page" in js
    assert "profileForm" not in js
    assert ".account-plan-grid>.membership-card:nth-child(4){grid-column:2/span 2}" in css
    assert ".account-plan-grid>.membership-card:nth-child(5){grid-column:4/span 2}" in css
