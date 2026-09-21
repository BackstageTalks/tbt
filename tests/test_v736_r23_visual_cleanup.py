from pathlib import Path
import copy
import json

from tbt.services.admin_storage import validate_ui_config

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
RESPONSIVE = (WEB / "responsive.js").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
BANNERS = json.loads((WEB / "config" / "banners.json").read_text(encoding="utf-8"))
BACKEND = (ROOT / "api" / "tbt" / "services" / "admin_storage.py").read_text(encoding="utf-8")


def test_r23_cleanup_survives_newer_release_patches():
    release_no = int(RELEASE["patch"].split("r", 1)[1])
    ui_no = int(UI["ui_patch"].split("r", 1)[1])
    assert release_no >= 23
    assert ui_no >= 23
    assert "BlinQ runtime patch 7.3.6-r23: legacy visual cleanup" in CSS


def test_retired_header_and_content_banner_dom_is_gone():
    for token in ("headerFeatureStrip", "bannerTop", "bannerMid", "bannerBottom"):
        assert token not in INDEX
    assert "feature-strip" not in INDEX


def test_retired_banner_configuration_and_tier_editor_are_gone():
    for key in ("content_rows", "header_cta", "creative_specs"):
        assert key not in UI
    assert "show_header_feature_strip" not in UI.get("dashboard", {})
    assert "snapshot_cards" not in UI.get("dashboard", {})
    assert "PREDICTION_TOOLBAR" not in UI["elements"]
    assert "SIDEBAR_PREDICTIONS" not in UI["elements"]
    assert "row_presets" not in UI.get("admin", {})
    assert "ads_help" not in BANNERS
    assert not any(item.get("kind") in {"header_slot", "large_banner"} for item in UI["elements"].values())
    for i in range(1, 6):
        hero = UI["elements"][f"HERO_BANNER_{i}"]
        assert hero["kind"] == "hero_banner"
        assert "access" not in hero and "click_access" not in hero
    for token in (
        "function renderHeaderSlots", "function renderBanners", "rowPresetMap",
        "data-admin-row-preset", "data-simple-banner-state", "data-banner-state-plan",
        "data-banner-preset", "Viditeľnosť podľa levelu",
    ):
        assert token not in APP


def test_current_advanced_prediction_controls_are_deliberately_kept():
    assert "admin-row-advanced" in APP
    assert "data-admin-hub-row-state" in APP
    assert "SHOW / BLUR / HIDE" in APP


def test_retired_drawer_api_and_obsolete_css_selectors_stay_removed():
    assert "closeMenu" not in APP
    assert "closeMenu" not in RESPONSIVE
    for token in (
        ".legacy-nav-hook", "#headerFeatureStrip", ".promo-zone", ".header-slot", ".admin-banner-workspace",
        ".admin-overview-v687", ".admin-console-v675", ".admin-accounts-toolbar-v669",
    ):
        assert token not in CSS


def test_backend_normalizes_retired_hero_membership_rules():
    assert 're.compile(r"^HERO_BANNER_[1-5]$")' in BACKEND
    stale = copy.deepcopy(UI)
    stale["elements"]["HERO_BANNER_1"]["access"] = {"rookie": "active"}
    stale["elements"]["HERO_BANNER_1"]["click_access"] = {"rookie": True}
    cleaned = validate_ui_config(stale)
    assert "access" not in cleaned["elements"]["HERO_BANNER_1"]
    assert "click_access" not in cleaned["elements"]["HERO_BANNER_1"]
