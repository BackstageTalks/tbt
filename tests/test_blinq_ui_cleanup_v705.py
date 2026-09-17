from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-lean-700.css").read_text(encoding="utf-8")

def test_home_has_no_search_filter_or_right_promo_rail():
    assert 'id="dashboardSearch"' not in INDEX
    assert 'id="dailyHubTournamentFilter"' not in INDEX
    assert 'id="dashboardRightRail"' not in INDEX
    assert '#dashboardRightRail{display:none!important}' in CSS

def test_header_has_upgrade_live_and_info_as_separate_controls():
    assert 'id="topUpgradeButton"' in INDEX
    assert 'id="insightShortcut"' in INDEX
    assert 'id="insightBell"' in INDEX
    assert "insightChannel:'info'" in APP
    assert "toggleInsightChannel('live')" in APP
    assert "toggleInsightChannel('info')" in APP

def test_bottom_membership_strip_is_links_only():
    assert 'vip-links-only' in APP
    render = APP.split('function renderVipRail(){',1)[1].split('function renderFooterConfig(){',1)[0]
    assert 'vip-cta' not in render

def test_active_navigation_uses_short_centered_underline():
    assert 'width:24px!important' in CSS
    assert 'transform:translateX(-50%)!important' in CSS
