import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_admin_layout_has_fixed_slot_inventory_and_access_states():
    cfg = _cfg()
    assert cfg["schema"] == 2
    elements = cfg["elements"]
    assert {f"HEADER_BANNER_{i}" for i in range(1, 4)} <= set(elements)
    assert {f"CONTENT_TOP_{i}" for i in range(1, 5)} <= set(elements)
    assert {f"CONTENT_BOTTOM_{i}" for i in range(1, 5)} <= set(elements)
    assert {"SIDEBAR_PROMO_1", "SIDEBAR_PROMO_2", "PRIME_PICKS_PANEL", "FOOTER_SYSTEM"} <= set(elements)
    contexts = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}
    valid = {"active", "locked", "blurred", "hidden"}
    for element in elements.values():
        assert contexts <= set(element["access"])
        assert set(element["access"].values()) <= valid
        assert element["access"]["trial"] == element["access"]["rookie"]
        assert "watermark" in element


def test_plan_catalogue_has_requested_default_terms_and_reserved_legend():
    plans = _cfg()["plans"]
    assert plans["trial"]["trial_hours"] == 72
    assert plans["trial"]["inherits"] == "rookie"
    assert plans["rookie"]["duration_days"] == 30
    assert plans["pro"]["duration_days"] == 30
    assert plans["elite"]["duration_days"] == 365
    assert plans["goat"]["lifetime"] is True
    assert plans["goat"]["duration_days"] is None
    assert plans["legend"]["enabled"] is False
    assert "admin" not in plans


def test_hide_ads_and_fallback_inventory_are_configured_without_collapsing_layout():
    cfg = _cfg()
    assert cfg["plans"]["rookie"]["hide_ads_allowed"] is False
    assert cfg["plans"]["pro"]["hide_ads_allowed"] is False
    assert cfg["plans"]["elite"]["hide_ads_allowed"] is True
    assert cfg["plans"]["goat"]["hide_ads_allowed"] is True
    assert cfg["ad_fallbacks"]["mode"] == "mixed"
    assert isinstance(cfg["ad_fallbacks"]["fallback_images"], list)
    for slot in [*(f"CONTENT_TOP_{i}" for i in range(1, 5)), *(f"CONTENT_BOTTOM_{i}" for i in range(1, 5))]:
        content = cfg["elements"][slot]["content"]
        assert "campaign_id" in content
        assert "advertiser_id" in content
        assert content["ad_hidden_fallback"] in {"auto", "rss", "image", "internal"}


def test_banner_analytics_contract_uses_viewport_threshold_and_campaign_identity():
    cfg = _cfg()
    assert cfg["analytics"]["impression_threshold"] == 0.5
    assert cfg["analytics"]["impression_ms"] == 1000
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "IntersectionObserver" in app_js
    assert "data-campaign-id" in app_js
    assert "unique_impressions" in app_js


def test_admin_runtime_secret_never_enters_web_bundle():
    web = "\n".join(
        (ROOT / "web" / name).read_text(encoding="utf-8")
        for name in ("index.html", "app.js", "auth.js", "ui-config.json")
    )
    assert "SUPABASE_SERVICE_ROLE_KEY" not in web
    assert "/api/v1/admin/users" in web


def test_admin_routes_and_runtime_config_are_server_side():
    app = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    auth = (ROOT / "api" / "tbt" / "services" / "auth.py").read_text(encoding="utf-8")
    assert 'route="v1/admin/users"' in app
    assert 'route="v1/admin/users/{user_id}/access"' in app
    assert 'route="v1/admin/ui-config"' in app
    assert 'route="v1/admin/banner-analytics"' in app
    assert 'route="v1/banner-events"' in app
    assert 'route="v1/content/news"' in app
    assert "app_metadata" in auth
    assert "timedelta(hours=72)" in auth


def test_rss_sources_live_in_backend_json_and_are_empty_until_owner_configures_them():
    content = json.loads((ROOT / "api" / "config" / "content.json").read_text(encoding="utf-8"))
    assert content["rss"]["enabled"] is True
    assert content["rss"]["refresh_minutes"] == 45
    assert content["rss"]["max_age_hours"] == 48
    assert content["rss"]["sources"] == []


def test_large_content_rows_use_only_fixed_supported_merge_presets():
    cfg = _cfg()
    assert cfg["content_rows"]["content_top"]["preset"] == "1+1+1+1"
    assert cfg["content_rows"]["content_bottom"]["preset"] == "1+1+1+1"
    assert set(cfg["admin"]["row_presets"]) == {"1+1+1+1", "2+2", "2+1+1", "1+1+2", "4"}
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "rowPresetMap" in app_js
    assert "adminTopRowPreset" in app_js
    assert "adminBottomRowPreset" in app_js


def test_campaigns_advertisers_and_rss_are_separate_runtime_entities():
    cfg = _cfg()
    assert isinstance(cfg["advertisers"], dict)
    assert isinstance(cfg["campaigns"], dict)
    assert cfg["rss"]["enabled"] is True
    assert len(cfg["rss"]["sources"]) == 2
    assert {row["id"] for row in cfg["rss"]["sources"]} == {"tennis_main", "tennis_backup"}
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "renderAdminCampaigns" in app_js
    assert "renderAdminFeeds" in app_js
    assert "campaignContent" in app_js


def test_virtual_future_permissions_are_configurable_without_changing_layout():
    elements = _cfg()["elements"]
    assert elements["VIP_TELEGRAM"]["kind"] == "feature"
    assert elements["FOOTBALL_ACCESS"]["kind"] == "feature"
    assert elements["VIP_TELEGRAM"]["access"]["elite"] == "active"
    assert elements["VIP_TELEGRAM"]["access"]["goat"] == "active"


def test_rookie_pick_entitlement_is_stable_across_filters():
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function rankedPredictions" in app_js
    assert "accessIndex:index" in app_js
    assert "Number.isInteger(m.accessIndex)" in app_js
    cfg = _cfg()["elements"]
    assert all(cfg[f"TOP_PICK_{i}"]["access"]["rookie"] == "active" for i in range(1, 4))
    assert all(cfg[f"TOP_PICK_{i}"]["access"]["rookie"] == "blurred" for i in range(4, 9))


def test_campaign_manager_supports_fixed_size_creative_variants():
    cfg = _cfg()
    specs = cfg["creative_specs"]
    assert specs["large_1"]["recommended"] == "1200 × 900 px"
    assert specs["large_2"]["recommended"] == "2400 × 900 px"
    assert specs["large_4"]["recommended"] == "2400 × 450 px"
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "data-campaign-image" in app_js
    assert "creative_mode:'full'" in app_js
    assert "show_copy:false" in app_js
    assert "creative-full" in app_js
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert ".promo-card.creative-full .promo-image" in css
    assert ".promo-card.no-copy .promo-copy" in css
