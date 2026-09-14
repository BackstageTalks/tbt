from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_release_and_cache_are_6600():
    cfg = json.loads(read("web/ui-config.json"))
    assert cfg["ui_revision"] == "6.7.4"
    assert cfg["revision"] == "6.7.4"
    assert 'RELEASE = "6.7.4"' in read("api/function_app.py")
    html = read("web/index.html")
    assert '/blinq.css?v=674' in html
    for asset in ("auth.js", "responsive.js", "app.js"):
        assert f'/{asset}?v=674' in html

def test_new_web_uses_one_design_system_not_legacy_css_stack():
    html = read("web/index.html")
    assert '/blinq.css?v=674' in html
    assert 'media="not all"' in html
    assert "premium-v2.css?v=" not in html
    assert "final-ui.css?v=" not in html
    css = read("web/blinq.css")
    assert ".header-top" in css
    assert ".daily-panel" in css
    assert ".vip-rail" in css

def test_hero_targets_runtime_markup():
    app = read("web/app.js")
    css = read("web/blinq.css")
    assert 'class="dashboard-hero-copy"' in app
    assert ".dashboard-hero-copy" in css
    assert "Dáta. Analýza." in read("web/ui-config.json")
    assert "Lepšie rozhodnutia." in read("web/ui-config.json")

def test_home_navigation_excludes_btts_and_has_search():
    app = read("web/app.js")
    html = read("web/index.html")
    assert ".filter(id=>id!=='btts')" in app
    assert "headerSearchInput" in html
    assert "mainNavigation" in html

def test_daily_hub_has_rich_player_and_tournament_identity():
    app = read("web/app.js")
    html = read("web/index.html")
    assert "hub-player-meta" in app
    assert "hub-flag" in app
    assert "hub-rank" in app
    assert "tournament_logo_id" in app
    assert "/api/v1/tournament-logo/" in app
    assert "dailyHubMetaDate" in html

def test_account_is_modal_and_admin_controls_are_reachable():
    html = read("web/index.html")
    app = read("web/app.js")
    assert 'id="accountDialog"' in html
    assert "openAccountDialog()" in app
    assert "adminQuickButton" in html
    assert "profileAdminLink" in html
    assert "publishUiConfig" in app
    assert "Bannery a odkazy" in app
