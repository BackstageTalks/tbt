from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_release_and_cache_are_current():
    cfg = json.loads(read("web/ui-config.json"))
    assert cfg["ui_revision"] == cfg["revision"] == "6.8.6"
    assert cfg["asset_revision"] == "6864"
    assert 'RELEASE = "6.8.6"' in read("api/function_app.py")
    html = read("web/index.html")
    for asset in ("blinq.css", "auth.js", "responsive.js", "app.js"):
        assert f'/{asset}?v={cfg["asset_revision"]}' in html

def test_new_web_uses_one_design_system_not_legacy_css_stack():
    html = read("web/index.html")
    cfg = json.loads(read('web/ui-config.json'))
    assert f"/blinq.css?v={cfg['asset_revision']}" in html
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
    assert "adminQuickButton" not in html
    assert "profileAdminLink" in html
    assert "publishUiConfig" in app
    assert "Bannery" in app
    assert "Mapa slotov · obsah" in app
