import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
APP = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
TIERS = json.loads((WEB / "config" / "membership-tiers.json").read_text(encoding="utf-8"))
SITE = json.loads((WEB / "config" / "site-content.json").read_text(encoding="utf-8"))
API = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")


def test_loading_and_normal_page_keep_blinq_watermarks_and_motion():
    asset_revision = str(UI["asset_revision"])
    patch = UI["ui_patch"].rsplit("r", 1)[-1]
    for asset in ("blinq-loader.webp", "blinq-loader-static.webp", "blinq-loader.gif"):
        assert f"/assets/{asset}?v={asset_revision}&p={patch}" in INDEX
    assert "prefers-reduced-motion: reduce" in INDEX
    assert "boot-splash.boot-splash-tennis::after" in CSS
    assert "display:none!important;content:none!important;animation:none!important" in CSS
    assert ".anti-share-watermarks{display:none!important}" in CSS
    assert "#dashboardHero::after" in CSS
    assert "/assets/blinq_logo.svg" in CSS
    assert "clip-path:none!important" in CSS


def test_player_and_tournament_fallbacks_stay_csp_safe():
    assert (WEB / "assets" / "missing_foto_m.webp").is_file()
    assert (WEB / "assets" / "missing_foto_w.webp").is_file()
    assert (WEB / "assets" / "tournament-fallbacks" / "tennis.svg").is_file()
    assert "document.addEventListener('error',handleAssetImageError,true)" in APP
    assert "data-player-photo" in APP
    assert "data-tournament-logo" in APP
    assert "onerror=" not in APP


def test_results_tournament_and_location_are_separate_and_location_is_explicit_only():
    assert "<th>Turnaj</th><th>Zápas</th>" in APP
    assert "tournamentIdentityHtml(r)" in APP
    assert "tournament-location" in APP
    assert "Location is rendered only when the API/provider exposes it explicitly." in APP
    assert "if(!location&&rawName.includes(','))" not in APP


def test_membership_copy_and_feature_lists_are_json_managed():
    for tier in ("rookie", "pro", "elite", "legend", "goat"):
        assert isinstance(TIERS["tiers"][tier].get("features"), list)
        assert TIERS["tiers"][tier]["features"]
    upgrade = SITE["ui_copy"]["upgrade"]
    assert upgrade["generic_badge"]["sk"] == "Upgrade členstva"
    assert "state.presentationConfig?.tiers?.tiers?.[id]?.features" in APP
    assert "lockedContext" in APP


def test_generic_upgrade_does_not_mark_required_level_but_locked_content_does():
    assert "showUpgradePrompt(plan,section)" in APP
    assert "showUpgradePrompt(accessUpgrade.dataset.upgradePlan||'elite',accessUpgrade.dataset.upgradeSection||'BlinQ',true)" in APP
    assert "required=Boolean(lockedContext&&idx===requiredIndex)" in APP
    assert "upgrade-account-role" not in APP
    assert "lockedContext?`<span class=\"upgrade-requires-pill is-required-context\"" in APP
    assert "upgrade-benefit-strip" not in APP.split("host.innerHTML=", 1)[1].split("host.querySelectorAll", 1)[0]


def test_detail_column_has_clean_end_without_arrow_glyph():
    row_block = APP.split("function dailyHubRow", 1)[1].split("function dailyHubLockedRow", 1)[0]
    assert 'aria-hidden="true">→</span>' not in row_block
    assert ".daily-hub-table .hub-action-cell .hub-detail" in CSS
    assert "width:56px!important" in CSS


def test_admin_system_surfaces_media_storage_and_live_checks():
    for label in ("PLAYER IMAGES", "TOURNAMENT LOGOS", "INFO STORAGE", "LIVE DATA"):
        assert label in APP
    assert "def _feed_asset_health" in API
    assert '"assets": asset_health' in API
    assert '"services": service_health' in API


def test_release_and_cache_revision_cannot_drift():
    revision = str(UI["revision"])
    asset_revision = str(UI["asset_revision"])
    release = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
    assert revision == "7.3.6"
    assert release["release"] == revision
    assert f'data-web-release="{revision}"' in INDEX
    patch = re.search(r'<meta name="blinq-web-patch" content="736-r(\d+)"', INDEX)
    assert patch, "missing web patch marker"
    patch_n = patch.group(1)
    assert f'/app.js?v={asset_revision}&p={patch_n}' in INDEX
    assert f'/blinq-app.css?v={asset_revision}&p={patch_n}' in INDEX
    refs = re.findall(r'(?:src|href)="(/[^"?#]+\.(?:js|css)\?v=(\d+)[^"]*)"', INDEX)
    assert refs, "expected versioned frontend assets"
    bad = [(ref, version) for ref, version in refs if version != asset_revision]
    assert not bad, bad
