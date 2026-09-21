import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_admin_layout_has_current_inventory_and_access_states():
    cfg = _cfg()
    assert cfg["schema"] == 2
    elements = cfg["elements"]
    assert {f"HERO_BANNER_{i}" for i in range(1, 6)} <= set(elements)
    assert {
        "PRIME_PICKS_PANEL", "TOP_DAILY_PANEL", "VALUE_PICKS_PANEL",
        "ACE_PICKS_PANEL", "SG_PICKS_PANEL", "DOUBLES_PANEL", "RESULTS_PANEL",
    } <= set(elements)
    retired = {
        "SIDEBAR_PROMO_1", "SIDEBAR_PROMO_2", "SIDEBAR_PROMO_3", "SIDEBAR_PROMO_4",
        "BTTS_BONUS_PANEL", "FOOTER_SYSTEM", "VIP_RAIL",
    }
    assert retired.isdisjoint(elements)
    assert not any(item.get("kind") in {"header_slot", "large_banner"} for item in elements.values())
    contexts = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}
    valid = {"active", "locked", "blurred", "hidden"}
    for element in elements.values():
        if element.get("kind") == "hero_banner":
            assert "access" not in element
            assert "click_access" not in element
        else:
            assert contexts <= set(element["access"])
            assert set(element["access"].values()) <= valid
            assert element["access"]["trial"] == element["access"]["rookie"]
        assert "watermark" in element


def test_plan_catalogue_has_requested_default_terms_and_active_legend():
    plans = _cfg()["plans"]
    assert plans["trial"]["enabled"] is False
    assert plans["trial"]["trial_hours"] == 0
    assert plans["trial"]["inherits"] == "rookie"
    assert plans["rookie"]["duration_days"] is None
    assert plans["rookie"]["unlimited"] is True
    assert plans["pro"]["duration_days"] == 30
    assert plans["elite"]["duration_days"] == 180
    assert plans["goat"]["lifetime"] is False
    assert plans["goat"]["unlimited"] is False
    assert plans["goat"]["duration_days"] == 365
    assert plans["legend"]["enabled"] is True
    assert plans["legend"]["duration_days"] == 365
    assert "admin" not in plans


def test_hide_ads_and_hero_fallback_inventory_are_configured_without_plan_gating():
    cfg = _cfg()
    assert cfg["plans"]["rookie"]["hide_ads_allowed"] is False
    assert cfg["plans"]["pro"]["hide_ads_allowed"] is False
    assert cfg["plans"]["elite"]["hide_ads_allowed"] is False
    assert cfg["plans"]["legend"]["hide_ads_allowed"] is False
    assert cfg["plans"]["goat"]["hide_ads_allowed"] is False
    assert cfg["ad_fallbacks"]["priority"] == ["active_advertisement", "blinq_internal"]
    assert cfg["ad_fallbacks"]["mode"] == "mixed"
    assert isinstance(cfg["ad_fallbacks"]["fallback_images"], list)
    for slot in (f"HERO_BANNER_{i}" for i in range(1, 6)):
        element = cfg["elements"][slot]
        content = element["content"]
        assert "campaign_id" not in content
        assert "advertiser_id" not in content
        assert content["ad_hidden_fallback"] in {"auto", "rss", "image", "internal"}
        assert "access" not in element and "click_access" not in element


def test_banner_analytics_contract_tracks_fixed_slots_without_campaign_manager():
    cfg = _cfg()
    assert cfg["analytics"]["impression_threshold"] == 0.5
    assert cfg["analytics"]["impression_ms"] == 1000
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "IntersectionObserver" in app_js
    assert "data-banner-slot" in app_js
    assert "BlinqAuth.bannerEvent" in app_js
    assert "renderAdminAnalytics" not in app_js


def test_admin_runtime_secret_never_enters_web_bundle():
    web = "\n".join(
        (ROOT / "web" / name).read_text(encoding="utf-8")
        for name in ("index.html", "app.js", "auth.js", "ui-config.json")
    )
    assert "FIREBASE_PRIVATE_KEY" not in web
    assert "FIREBASE_CLIENT_EMAIL" not in web
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
    assert "No membership claim means the permanent free base tier, not a trial." in auth


def test_rss_sources_live_in_backend_json_and_are_empty_until_owner_configures_them():
    content = json.loads((ROOT / "api" / "config" / "content.json").read_text(encoding="utf-8"))
    assert content["rss"]["enabled"] is True
    assert content["rss"]["refresh_minutes"] == 45
    assert content["rss"]["max_age_hours"] == 48
    assert content["rss"]["sources"] == []


def test_legacy_header_and_content_banner_visuals_are_removed():
    cfg = _cfg()
    assert "content_rows" not in cfg
    assert "header_cta" not in cfg
    assert "creative_specs" not in cfg
    assert "row_presets" not in cfg.get("admin", {})
    assert not any(item.get("kind") in {"header_slot", "large_banner"} for item in cfg["elements"].values())
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function renderHeaderSlots" not in app_js
    assert "function renderBanners" not in app_js
    assert "rowPresetMap" not in app_js
    assert "data-admin-row-preset" not in app_js
    assert "data-banner-preset" not in app_js


def test_campaign_manager_is_retired_and_rss_is_not_exposed_in_public_admin():
    cfg = _cfg()
    assert "advertisers" not in cfg
    assert "campaigns" not in cfg
    assert cfg["rss"]["enabled"] is False
    assert cfg["rss"]["sources"] == []
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "renderAdminCampaigns" not in app_js
    assert "campaignContent" not in app_js
    assert "data-campaign-field" not in app_js
    route = app_js.split("function renderAdminRoute()", 1)[1].split("function rerenderAdmin", 1)[0]
    assert "RSS feeds" not in route


def test_retired_virtual_permissions_are_removed_from_runtime_config():
    elements = _cfg()["elements"]
    assert "VIP_TELEGRAM" not in elements
    assert "FOOTBALL_ACCESS" not in elements
    assert "VIP_RAIL" not in elements


def test_rookie_pick_entitlement_is_stable_across_filters():
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function rankedPredictions" in app_js
    assert "accessIndex:index" in app_js
    assert "Number.isInteger(m.accessIndex)" in app_js
    cfg = _cfg()["elements"]
    assert all(cfg[f"TOP_PICK_{i}"]["access"]["rookie"] == "active" for i in range(1, 4))
    assert all(cfg[f"TOP_PICK_{i}"]["access"]["rookie"] == "blurred" for i in range(4, 9))


def test_hero_manager_uses_current_desktop_mobile_creative_contract():
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "data-admin-hero-count" in app_js
    assert "data-admin-hero-seconds" in app_js
    assert 'data-simple-banner-field="image_url"' in app_js
    assert 'data-simple-banner-field="mobile_image_url"' in app_js
    assert "1920×640" in app_js
    assert "1080×720" in app_js
    assert "data-campaign-image" not in app_js


def test_dashboard_market_structure_matches_approved_order_and_rules():
    cfg = _cfg()
    rules = cfg["market_rules"]
    assert rules["prime"]["market"] == "match_winner"
    assert rules["prime"]["objective"] == "accuracy_first"
    assert rules["prime"]["min_win_probability"] == 0.68
    assert rules["prime"]["preferred_probability"] == 0.85
    assert rules["prime"]["minimum_dashboard_count"] == 5
    assert rules["prime"]["min_data_depth"] == 0.80
    assert rules["prime"]["min_surface_matches"] == 5
    assert rules["prime"]["preferred_min_odds"] is None
    assert rules["prime"]["preferred_max_odds"] == 1.49
    assert rules["prime"]["hard_odds_band"] is True
    assert rules["prime"]["max_negative_expected_value"] is None
    assert rules["prime"]["limit"] == 30
    assert rules["top_daily"]["label"] == "TOP Predictions"
    assert rules["top_daily"]["limit"] is None
    assert rules["top_daily"]["presentation_preview_limit"] == 10
    assert rules["top_daily"]["target_count"] == 10
    assert rules["top_daily"]["preferred_probability"] == 0.80
    assert rules["top_daily"]["secondary_probability"] == 0.78
    assert rules["top_daily"]["standard_probability"] == 0.76
    assert rules["top_daily"]["confidence_tiers"] == [0.80, 0.78, 0.76, 0.74, 0.72, 0.70, 0.68]
    assert rules["top_daily"]["min_probability"] == 0.68
    assert rules["top_daily"]["min_odds"] == 1.50
    assert rules["top_daily"]["max_odds"] is None
    assert rules["top_daily"]["min_edge"] is None
    assert rules["top_daily"]["min_expected_value"] is None
    assert rules["top_daily"]["edge_ev_role"] == "diagnostic_only"
    assert rules["top_daily"]["objective"] == "confidence_first"
    assert rules["value"]["selection_mode"] == "probability_plus_close_odds"
    assert rules["value"]["min_probability"] == 0.60
    assert rules["value"]["min_data_depth"] == 0.75
    assert rules["value"]["min_surface_matches"] == 3
    assert rules["value"]["min_odds"] == 1.80
    assert rules["value"]["min_edge"] is None
    assert rules["value"]["min_expected_value"] is None
    assert rules["value"]["limit"] is None
    assert rules["value"]["presentation_preview_limit"] == 10
    assert rules["doubles"]["model_branch"] == "separate"
    assert rules["match_winner_assignment"]["exclusive"] is True
    assert rules["match_winner_assignment"]["priority"] == ["value", "prime", "top_daily"]
    assert set(rules["ace"]["markets"]) == {"aces", "double_faults"}
    assert set(rules["sg"]["markets"]) == {"sets", "games"}
    assert "btts" not in rules
    dashboard = cfg["dashboard"]
    assert set(dashboard["section_order"]) == {"prime", "top_daily", "value", "doubles", "ace", "sg", "results"}
    assert len(dashboard["section_order"]) == 7
    assert dashboard["visible_slots"] == 6
    assert dashboard["user_switches"] is False


def test_banner_adaptation_and_watermark_controls_are_exposed_in_admin():
    cfg = _cfg()
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    assert "mobile_image_url" in app_js
    assert "image_fit" in app_js
    assert "image_position" in app_js
    assert "data-simple-banner-field" in app_js
    assert "data-admin-watermark" not in app_js
    assert ".hero-slide-image{object-fit:cover}" in css
    assert ".hero-slide-image.fit-contain{object-fit:contain}" in css
    assert ".hero-slide-image.pos-left{object-position:left}" in css
    assert not any(key.startswith("SIDEBAR_PROMO_") for key in cfg["elements"])


def test_current_section_access_inventory_and_public_header_are_clean():
    cfg = _cfg()
    nav_items = sorted(
        [item for item in cfg["elements"].values() if item.get("kind") == "navigation"],
        key=lambda item: item["order"],
    )
    nav = {item["content"]["route"]: item["content"]["label"] for item in nav_items}
    assert list(nav) == ["prime", "top_daily", "value", "doubles", "ace", "sg", "results"]
    assert nav["prime"] == "Short Odds"
    assert "predictions" not in nav  # old SIDEBAR_PREDICTIONS access stub is retired
    for removed in ("tournaments", "players", "stats", "model", "backtests", "account"):
        assert removed not in nav
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert '<nav class="reference-navigation"' in html
    assert 'data-route="predictions"' in html and 'data-route="results"' in html
    assert 'id="adminNavigationWrap"' not in html
    assert "btts" not in nav
    assert "renderAdminPerformance" not in app
    route = app.split("function renderAdminRoute()", 1)[1].split("function rerenderAdmin", 1)[0]
    for tab in ("accounts", "levels", "layout", "banners", "telegram", "insights", "system"):
        assert f"['{tab}'" in route
    for retired in ("campaigns", "analytics", "audit", "support"):
        assert f"['{retired}'" not in route
