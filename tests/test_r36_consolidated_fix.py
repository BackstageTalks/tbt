import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "api" / "tbt" / "services" / "auth.py").read_text(encoding="utf-8")
FUNCTION_APP = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
RESPONSIVE = (WEB / "responsive.js").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
INACTIVITY = (ROOT / "api" / "tbt" / "services" / "account_inactivity.py").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))


def test_r36_release_identity():
    assert RELEASE["release"] == "7.3.6"
    assert RELEASE["patch"] == "736-r47"
    assert UI["ui_patch"] == "736-r47"


def test_real_rookie_has_ui_and_server_admin_guards():
    assert 'id="profileAdminLink"' in INDEX and 'type="button" hidden' in INDEX
    assert "profileAdmin.hidden=!isAdminAccount()" in APP
    assert "if(route==='admin'&&!isAdminAccount()) route='predictions'" in APP
    assert ".profile-menu button[hidden]{display:none!important}" in CSS
    assert 'str(app.get("role") or "").strip().lower() == "admin"' in AUTH
    assert 'return None, response({"error": "forbidden"}, 403)' in FUNCTION_APP
    assert "profile-preview-context" not in INDEX


def test_rookie_static_offer_is_random_daily_and_results_are_legend_plus():
    tabs = UI["dashboard"]["daily_hub"]["tabs"]
    for tab in ("daily", "prime", "value"):
        rule = tabs[tab]["plans"]["rookie"]
        assert rule["selection_mode"] == "stable_random"
        assert int(rule["visible_rows"]) == 1
        assert rule["blur_remaining"] is True
    results = UI["elements"]["SIDEBAR_RESULTS"]["access"]
    assert results["rookie"] == results["pro"] == results["elite"] == "locked"
    assert results["legend"] == results["goat"] == "active"


def test_live_and_locked_detail_copy_are_unambiguous():
    assert "shortcutLabel.textContent=liveEligible?(confirmed?'CONFIRMED':watching?'WATCH':'RADAR'):'RADAR'" in APP
    assert "LIVE ELITE" not in APP
    assert "hub-detail is-locked" in APP
    assert "<i aria-hidden=\"true\">🔒</i>" in APP
    assert ".hub-detail.is-locked>small{display:none!important}" in CSS


def test_player_photo_fallback_chain_is_not_short_circuited():
    assert "/assets/missing_foto_m.webp" in APP
    assert "/assets/missing_foto_w.webp" in APP
    assert "img.dataset.fallbackApplied='1'" in APP
    assert "if (img.matches('[data-player-photo]')) return;" in RESPONSIVE
    assert (WEB / "assets" / "missing_foto_m.webp").is_file()
    assert (WEB / "assets" / "missing_foto_w.webp").is_file()


def test_inactivity_deactivation_waits_full_warning_window_after_delivery():
    assert 'warning_days = int(raw.get("warning_days", 7))' in INACTIVITY
    assert 'notify_user = raw.get("notify_user", True) is not False' in INACTIVITY
    assert 'inactivity_deactivation_warning_sent_at' in INACTIVITY
    assert 'now >= warning_sent_at + timedelta(days=policy["warning_days"])' in INACTIVITY
    assert 'and warning_already_sent' in INACTIVITY
