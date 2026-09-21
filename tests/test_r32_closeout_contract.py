import json
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
APP = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")


def test_r32_identity_background_and_loader_contract():
    release = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
    theme = json.loads((WEB / "config" / "site-theme.json").read_text(encoding="utf-8"))
    banners = json.loads((WEB / "config" / "banners.json").read_text(encoding="utf-8"))
    assert release["patch"] == UI["ui_patch"] == "736-r40"
    assert 'content="736-r40"' in INDEX
    assert (WEB / "assets" / "blinq_page_background.webp").is_file()
    assert theme["background"]["image"] == "/assets/blinq_page_background.webp"
    assert banners["main_banner"]["slides"][0]["site_background_url"] == "/assets/blinq_page_background.webp"
    assert "/assets/blinq_loading_r29.svg?v=7360&p=40" in INDEX
    assert (WEB / "assets" / "blinq_loading_r29.svg").is_file()
    # Loader background stays untouched even though the page/auth background changed.
    assert 'boot-splash.boot-splash-tennis' in CSS
    assert 'url("/assets/blinq_background.webp")' in CSS


def test_r32_top_short_odds_boundary_is_gapless_and_only_probability_relaxes():
    market = (ROOT / "api" / "tbt" / "services" / "market_selection.py").read_text(encoding="utf-8")
    top = UI["market_rules"]["top_daily"]
    assert "PRIME_MAX_ODDS_EXCLUSIVE = 1.50" in market
    assert "TOP_FALLBACK_MIN_ODDS = 1.50" in market
    assert "TOP_DYNAMIC_FALLBACK_MIN_PROBABILITY = 0.65" in market
    assert top["min_odds"] == 1.5
    assert top["fallback_min_odds"] == 1.5
    assert [x["min_probability"] for x in top["dynamic_fallback_tiers"]] == [.67, .66, .65]
    assert {x["min_odds"] for x in top["dynamic_fallback_tiers"]} == {1.5}
    assert UI["market_rules"]["match_winner_assignment"]["exclusive"] is True
    assert UI["market_rules"]["match_winner_assignment"]["priority"][0] == "value"


def test_r32_results_are_public_categories_only_and_admin_window_is_configurable():
    engine = (ROOT / "api" / "tbt" / "services" / "engine.py").read_text(encoding="utf-8")
    entitlements = (ROOT / "api" / "tbt" / "services" / "entitlements.py").read_text(encoding="utf-8")
    assert 'PUBLIC_RESULT_SECTIONS = {"top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}' in engine
    assert 'str(p.get("section") or "").strip().lower() in PUBLIC_RESULT_SECTIONS' in engine
    assert '"model"' not in engine.split("PUBLIC_RESULT_SECTIONS =", 1)[1].split("\n", 1)[0]
    for value in ('"24h": 24', '"48h": 48', '"3d": 72', '"7d": 168', '"14d": 336', '"30d": 720', '"all": None'):
        assert value in entitlements
    assert "data-admin-results-window" in APP
    assert "24H · 48H · 3D · 7D · 14D · 30D · ALL" in APP
    assert "function resultsLockedCard()" in APP
    assert "firstResultsUnlockPlan()" in APP
    assert "restrictedResultsRoute" in APP


def test_r32_detail_info_live_and_visual_cleanup_contract():
    validate_ui_config(UI)
    assert "data-admin-detail-plan" in APP
    assert "data-admin-detail-section" in APP
    assert "match-detail-lock-icon" in CSS
    assert "Ranking trend" not in APP and "Trend rebríčka" not in APP
    assert "Prečo BlinQ" not in APP and "Why BlinQ" not in APP
    assert "dailyHubBoardNotice" not in INDEX
    assert "tg-panel-mark" not in APP
    assert "dialog-meta{display:none!important}" in CSS
    assert "Preserve the established detail-card visual; improve only lower-panel readability." in CSS
    assert "info_min_level" in APP and "live_min_level" in APP
    assert "save-info-access" in APP and "save-live-access" in APP
    assert "is-access-locked" in APP
    assert "Aktualizácia modelu: —" in INDEX
    assert "@keyframes blinqStatusBreath" in CSS


def test_r32_custom_email_uses_real_blinq_logo_and_csp_safe_action_page():
    email = (ROOT / "api" / "tbt" / "services" / "auth_email.py").read_text(encoding="utf-8")
    function_app = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    auth_js = (WEB / "auth.js").read_text(encoding="utf-8")
    action_html = (WEB / "auth" / "action" / "index.html").read_text(encoding="utf-8")
    swa = json.loads((WEB / "staticwebapp.config.json").read_text(encoding="utf-8"))
    logo = ROOT / "api" / "tbt" / "assets" / "blinq_logo_email.png"
    assert logo.is_file() and logo.stat().st_size > 10_000
    assert 'src="cid:blinq-logo"' in email
    assert 'blinq_logo_email.png' in email
    assert 'cid="<blinq-logo>"' in email
    assert '@app.route(route="v1/auth/email", methods=["POST"])' in function_app
    assert "send_blinq_action_email" in function_app
    assert "/api/v1/auth/email" in auth_js
    assert "sendOobCode" not in auth_js
    assert '<img class="logo" src="/assets/blinq_logo.svg" alt="BlinQ">' in action_html
    assert '<script src="/auth/action/action.js?v=7360&p=40"></script>' in action_html
    assert '<script>' not in action_html
    assert any(route.get("route") == "/auth/action" and route.get("rewrite") == "/auth/action/index.html" for route in swa["routes"])
