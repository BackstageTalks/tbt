from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_and_cache_are_6553():
    cfg = json.loads(read("web/ui-config.json"))
    assert cfg["ui_revision"] == "6.5.53"
    assert cfg["revision"] == "6.5.53"
    assert 'RELEASE = "6.5.53"' in read("api/function_app.py")
    html = read("web/index.html")
    for asset in ("styles.css", "responsive.css", "premium.css", "premium-v2.css", "final-ui.css", "auth.js", "responsive.js", "app.js"):
        assert f'/{asset}?v=6553' in html


def test_final_ui_is_loaded_last_and_beats_legacy_specificity():
    html = read("web/index.html")
    assert html.index("premium-v2.css?v=6553") < html.index("final-ui.css?v=6553")
    css = read("web/final-ui.css")
    # Earlier premium.css historically used body#blinqPremium#blinqPremium + !important.
    # The final layer must meet/exceed that specificity or visual regressions silently return.
    assert "body#blinqPremium#blinqPremium .header-primary" in css
    assert "body#blinqPremium#blinqPremium .top-navigation" in css
    assert "body#blinqPremium#blinqPremium .daily-hub-table td" in css


def test_hero_targets_real_runtime_markup_not_obsolete_selector():
    app = read("web/app.js")
    css = read("web/final-ui.css")
    assert 'class="dashboard-hero-copy"' in app
    assert ".dashboard-hero-stage .dashboard-hero-copy" in css
    assert ".dashboard-hero-stage .hero-copy" not in css
    assert "Dáta. Analýza." in read("web/ui-config.json")
    assert "Lepšie rozhodnutia." in read("web/ui-config.json")


def test_home_navigation_excludes_btts_and_has_search_in_navigation_row():
    app = read("web/app.js")
    html = read("web/index.html")
    css = read("web/final-ui.css")
    assert ".filter(id=>id!=='btts')" in app
    assert "headerSearchInput" in html
    assert "grid-template-columns:minmax(0,1fr) 280px" in css
    assert "[['predictions','Prehľad','⌂']" in app


def test_daily_hub_has_rich_player_and_tournament_identity():
    app = read("web/app.js")
    html = read("web/index.html")
    assert "hub-player-meta" in app
    assert "hub-flag" in app
    assert "hub-rank" in app
    assert "hub-tour" in app
    assert "tournament_logo_id" in app
    assert "/api/v1/tournament-logo/" in app
    assert "dailyHubMetaDate" in html
    assert "dailyHubMetaDate" in app


def test_account_is_modal_and_admin_controls_are_still_reachable():
    html = read("web/index.html")
    app = read("web/app.js")
    css = read("web/final-ui.css")
    assert '<dialog aria-labelledby="accountDialogTitle" class="account-dialog" id="accountDialog">' in html
    assert "openAccountDialog()" in app
    assert "adminQuickButton" in html
    assert "profileAdminLink" in html
    assert "publishUiConfig" in app
    assert "Save draft" in app
    assert "Banners & links" in app
    assert "body#blinqPremium#blinqPremium .admin-tabs" in css
