from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web/blinq.css").read_text(encoding="utf-8")
UI = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
MEMBERSHIP = json.loads((ROOT / "web/membership-links.json").read_text(encoding="utf-8"))
BACKEND = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
ADMIN_STORAGE = (ROOT / "api/tbt/services/admin_storage.py").read_text(encoding="utf-8")


def test_release_cache_exactly_677():
    assert UI["ui_revision"] == "6.7.8"
    assert UI["revision"] == "6.7.8"
    assert 'RELEASE = "6.7.8"' in BACKEND
    for asset in ("styles.css", "responsive.css", "premium.css", "blinq.css", "auth.js", "responsive.js", "app.js"):
        assert f"/{asset}?v=678" in INDEX


def test_top_upgrade_and_admin_buttons_are_removed_but_admin_stays_in_profile_menu():
    assert 'id="topUpgradeButton"' not in INDEX
    assert 'id="adminQuickButton"' not in INDEX
    assert 'id="profileAdminLink"' in INDEX
    assert "const profileAdmin=$('profileAdminLink')" in APP


def test_header_profile_contains_requested_account_information():
    for node_id in ("profileTelegram", "profileRegisteredEmail", "profilePlan", "profileRemaining"):
        assert f'id="{node_id}"' in INDEX
    assert "profileTelegram.textContent" in APP
    assert "profileRegisteredEmail.textContent" in APP
    assert "profileRemaining.textContent" in APP
    assert "min-width:270px!important" in CSS


def test_account_modal_has_inline_profile_no_standalone_telegram_panel():
    assert 'account-modal-main-card' in APP
    assert 'account-profile-facts' in APP
    assert 'Registrovaný e-mail' in APP
    assert 'Telegram nick' in APP
    assert '<details class="account-modal-profile"' not in APP
    assert 'Zabezpečenie účtu' in APP


def test_level_layout_is_two_plus_two_plus_centered_goat_and_avatar_pairs():
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))!important' in CSS
    assert '.account-modal-plan.plan-goat{grid-column:1/-1!important;width:calc(50% - 5.5px)!important;justify-self:center!important' in CSS
    assert '.account-plan-grid>.membership-card.plan-goat{grid-column:1/-1!important;width:calc(50% - 6.5px)!important;justify-self:center!important' in CSS
    assert 'planAvatarPairHtml(id,p)' in APP
    assert 'entry.w' in APP and 'entry.m' in APP


def test_membership_copy_cta_and_links_are_json_managed_and_exact():
    plans = MEMBERSHIP["plans"]
    assert plans["pro"]["payment_url"] == "https://backstagetalks.tipsterpage.com/sk0y2du0/sk"
    assert plans["elite"]["payment_url"] == "https://backstagetalks.tipsterpage.com/qYBLx1L0/sk"
    for pid in ("rookie", "pro", "elite", "legend", "goat"):
        for field in ("label", "card_title", "description", "cta_label"):
            assert field in plans[pid]
    assert "p.cta_label" in APP and "p.description" in APP and "p.card_title" in APP
    assert "ONLINE PURCHASE NOT OPEN YET" not in APP


def test_daily_hub_requested_labels_results_and_elite_lock_are_in_code():
    assert '<h2>Dnešné predikcie <span>BlinQ Intelligence</span></h2>' in INDEX
    assert "daily-hub-results" in APP
    assert "Zobraziť celú ponuku" in APP
    assert "showUpgradePrompt('elite'" in APP
    tabs = UI["dashboard"]["daily_hub"]["tabs"]
    assert tabs["daily"]["label"] == "Prehľad"
    assert tabs["top"]["label"] == "TOP"
    assert tabs["value"]["label"] == "Value"


def test_user_facing_config_is_normalized_away_from_tipy_bety_picks_bets():
    ui_text = json.dumps(UI, ensure_ascii=False)
    assert not re.search(r"\b(?:tipy|bety)\b", ui_text, flags=re.I)
    for phrase in ("Top Bets", "Prime Picks", "Value Picks", "Premium Picks", "News · Picks · Discussions"):
        assert phrase not in ui_text
    assert "News · Predictions · Discussions" in ui_text


def test_vip_rail_is_not_hardcoded_and_is_fully_json_admin_managed():
    assert '<section id="vipRail" class="vip-rail"' in INDEX
    assert '<strong>BlinQ VIP</strong>' not in INDEX
    vip = UI["elements"]["VIP_RAIL"]
    assert vip["kind"] == "large_banner" and vip["zone"] == "vip_rail"
    for field in ("headline", "text", "button_text", "link", "image_url", "mobile_image_url", "benefit_1_title", "benefit_1_text", "benefit_2_title", "benefit_2_text", "benefit_3_title", "benefit_3_text"):
        assert field in vip["content"]
    assert "function renderVipRail()" in APP
    assert "bannerLibraryButton('VIP_RAIL',1,'vip')" in APP
    for field in ("benefit_1_title", "benefit_2_title", "benefit_3_title"):
        assert f'data-simple-banner-field="{field}"' in APP


def test_all_banner_editors_support_background_text_cta_and_access():
    for field in ("headline", "text", "button_text", "link", "image_url", "mobile_image_url", "image_fit", "image_position"):
        assert f'data-simple-banner-field="{field}"' in APP
    assert "renderBannerAccessMatrix" in APP
    assert "HEADER_BANNER_1" in APP and "HERO_BANNER_1" in APP and "CONTENT_TOP_1" in APP and "VIP_RAIL" in APP


def test_footer_text_and_links_are_json_managed():
    footer = UI["footer"]
    assert footer["copyright"] == "© 2026 BlinQ"
    assert footer["system_status"] == "Všetky systémy funkčné"
    assert [x["id"] for x in footer["links"]] == ["how_blinq_works", "methodology", "model_data", "faq", "responsible_use"]
    assert "state.ui?.footer?.links" in APP
    assert "function renderFooterConfig()" in APP


def test_tournament_fallback_and_flags_are_present():
    assert "family='CHALLENGER'" in APP
    assert "family='WTA'" in APP and "family='ATP'" in APP and "family='ITF'" in APP
    assert "const countryAlpha3To2" in APP
    assert "SVK:'SK'" in APP and "CZE:'CZ'" in APP and "USA:'US'" in APP
    assert "normalizeCountryCode" in APP


def test_admin_backend_endpoints_and_firestore_fallback_are_real_code_paths():
    for route in (
        'route="v1/admin/diagnostics"', 'route="v1/admin/users"',
        'route="v1/admin/users/{user_id}/access"', 'route="v1/admin/users/{user_id}/metadata"',
        'route="v1/admin/ui-config"', 'route="v1/admin/banner-analytics"'):
        assert route in BACKEND
    assert "class _FirestoreTableAdapter" in ADMIN_STORAGE
    assert 'backend = "azure_table" if azure_available else "firestore" if firestore_available else "unavailable"' in ADMIN_STORAGE
    assert "VIP_RAIL" in ADMIN_STORAGE


def test_admin_visual_polish_layer_is_present_and_bounded():
    assert "BlinQ 6.7.7 — strictly validated final visual corrections" in CSS
    assert ".admin-banner-workspace{grid-template-columns:minmax(235px,280px) minmax(0,1fr)!important" in CSS
    assert ".admin-banner-library{max-height:calc(100vh - 210px)!important" in CSS
    assert ".admin-form-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important" in CSS
