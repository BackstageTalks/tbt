from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_visible_header_search_is_removed_but_runtime_hook_survives():
    html = read("web/index.html")
    header = html.split('<div class="header-actions">', 1)[1].split('</div>', 1)[0]
    assert "global-search-top" not in header
    assert 'id="headerSearchInput"' in html
    assert 'aria-hidden="true"' in html

def test_prime_is_disabled_by_release_default():
    cfg = json.loads(read("web/ui-config.json"))
    assert cfg["dashboard"]["daily_hub"]["tabs"]["prime"]["enabled"] is False
    assert cfg["dashboard"]["sections"]["prime"]["dashboard_enabled"] is False
    assert cfg["dashboard"]["sections"]["prime"]["sidebar_enabled"] is False

def test_admin_has_clear_operational_tabs_and_global_daily_toggle():
    app = read("web/app.js")
    assert "['accounts','Používatelia','Level · platnosť']" in app
    assert "['layout','Denná ponuka','Levely · riadky']" in app
    assert "['banners','Bannery','Mapa slotov · obsah']" in app
    assert 'data-admin-hub-global-field="enabled"' in app
    assert "adminTab:'overview'" in app

def test_tournament_logo_has_tier_fallback_and_failure_css():
    app = read("web/app.js")
    css = read("web/blinq.css")
    assert "function tournamentFallbackBadge(row)" in app
    assert "row?.competition||row?.tournament_level" in app
    assert "CHALLENGER" in app
    assert "[MW](?:15|25|35|50|75|100)" in app
    assert ".hub-tournament-logo.logo-failed .hub-logo-fallback" in css
    assert ".hub-logo-code" in css

def test_daily_board_readability_rules_are_present():
    css = read("web/blinq.css")
    assert ".daily-hub-table td{height:82px!important" in css
    assert ".hub-tournament-logo,.hub-tour-logo{width:52px!important" in css
    assert ".hub-player-copy>b{font-size:12.5px!important" in css
