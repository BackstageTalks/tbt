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
    assert {f"CONTENT_MID_{i}" for i in range(1, 5)} <= set(elements)
    assert {f"CONTENT_BOTTOM_{i}" for i in range(1, 5)} <= set(elements)
    assert {
        "SIDEBAR_PROMO_1", "SIDEBAR_PROMO_2", "SIDEBAR_PROMO_3",
        "PRIME_PICKS_PANEL", "TOP_DAILY_PANEL", "VALUE_PICKS_PANEL",
        "ACE_PICKS_PANEL", "SG_PICKS_PANEL", "DOUBLES_PANEL", "BTTS_BONUS_PANEL", "FOOTER_SYSTEM",
    } <= set(elements)
    contexts = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}
    valid = {"active", "locked", "blurred", "hidden"}
    for element in elements.values():
        assert contexts <= set(element["access"])
        assert set(element["access"].values()) <= valid
        assert element["access"]["trial"] == element["access"]["rookie"]
        assert "watermark" in element


def test_plan_catalogue_has_requested_default_terms_and_active_legend():
    plans = _cfg()["plans"]
    assert plans["trial"]["trial_hours"] == 72
    assert plans["trial"]["inherits"] == "rookie"
    assert plans["rookie"]["duration_days"] == 30
    assert plans["pro"]["duration_days"] == 30
    assert plans["elite"]["duration_days"] == 180
    assert plans["goat"]["lifetime"] is True
    assert plans["goat"]["duration_days"] is None
    assert plans["legend"]["enabled"] is True
    assert plans["legend"]["duration_days"] == 365
    assert "admin" not in plans


def test_hide_ads_and_fallback_inventory_are_configured_without_collapsing_layout():
    cfg = _cfg()
    assert cfg["plans"]["rookie"]["hide_ads_allowed"] is False
    assert cfg["plans"]["pro"]["hide_ads_allowed"] is False
    assert cfg["plans"]["elite"]["hide_ads_allowed"] is False
    assert cfg["plans"]["legend"]["hide_ads_allowed"] is False
    assert cfg["plans"]["goat"]["hide_ads_allowed"] is False
    assert cfg["ad_fallbacks"]["priority"] == ["active_advertisement", "rss_news", "blinq_internal"]
    assert cfg["ad_fallbacks"]["mode"] == "mixed"
    assert isinstance(cfg["ad_fallbacks"]["fallback_images"], list)
    for slot in [
        *(f"CONTENT_TOP_{i}" for i in range(1, 5)),
        *(f"CONTENT_MID_{i}" for i in range(1, 5)),
        *(f"CONTENT_BOTTOM_{i}" for i in range(1, 5)),
    ]:
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
    assert "timedelta(hours=72)" in auth


def test_rss_sources_live_in_backend_json_and_are_empty_until_owner_configures_them():
    content = json.loads((ROOT / "api" / "config" / "content.json").read_text(encoding="utf-8"))
    assert content["rss"]["enabled"] is True
    assert content["rss"]["refresh_minutes"] == 45
    assert content["rss"]["max_age_hours"] == 48
    assert content["rss"]["sources"] == []


def test_large_content_rows_use_only_fixed_supported_merge_presets():
    cfg = _cfg()
    assert set(cfg["content_rows"]) == {"content_top", "content_mid", "content_bottom"}
    supported = {"1+1+1+1", "2+2", "2+1+1", "1+1+2", "4"}
    assert all(cfg["content_rows"][zone]["preset"] in supported for zone in cfg["content_rows"])
    assert all(isinstance(cfg["content_rows"][zone]["enabled"], bool) for zone in cfg["content_rows"])
    assert set(cfg["admin"]["row_presets"]) == supported
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "rowPresetMap" in app_js
    assert "data-admin-row-enabled" in app_js
    assert "data-admin-row-preset" in app_js


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
    assert specs["large_1"]["recommended"] == "1200 × 300 px"
    assert specs["large_2"]["recommended"] == "2400 × 300 px"
    assert specs["large_4"]["recommended"] == "2400 × 150 px"
    assert specs["large_1"]["minimum"] == "800 × 200 px"
    assert specs["large_4"]["safe_area"] == "center 90%"
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "data-campaign-image" in app_js
    assert "creative_mode:'full'" in app_js
    assert "show_copy:false" in app_js
    assert "creative-full" in app_js
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert ".promo-card.creative-full .promo-image" in css
    assert ".promo-card.no-copy .promo-copy" in css


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
    assert rules["prime"]["preferred_min_odds"] == 1.20
    assert rules["prime"]["preferred_max_odds"] == 1.50
    assert rules["prime"]["hard_odds_band"] is False
    assert rules["prime"]["max_negative_expected_value"] == -0.03
    assert rules["prime"]["limit"] == 30
    assert rules["top_daily"]["label"] == "Top Bets"
    assert rules["top_daily"]["limit"] is None
    assert rules["top_daily"]["presentation_preview_limit"] == 10
    assert rules["top_daily"]["target_count"] == 10
    assert rules["top_daily"]["preferred_probability"] == 0.80
    assert rules["top_daily"]["secondary_probability"] == 0.78
    assert rules["top_daily"]["standard_probability"] == 0.76
    assert rules["top_daily"]["confidence_tiers"] == [0.80, 0.78, 0.76, 0.74, 0.72, 0.70, 0.68]
    assert rules["top_daily"]["min_probability"] == 0.68
    assert rules["top_daily"]["min_odds"] == 1.20
    assert rules["top_daily"]["max_odds"] is None
    assert rules["top_daily"]["min_edge"] is None
    assert rules["top_daily"]["min_expected_value"] is None
    assert rules["top_daily"]["edge_ev_role"] == "diagnostic_only"
    assert rules["top_daily"]["objective"] == "confidence_first"
    assert rules["value"]["selection_mode"] == "edge_ev_first"
    assert rules["value"]["min_probability"] == 0.55
    assert rules["value"]["min_data_depth"] == 0.75
    assert rules["value"]["min_surface_matches"] == 3
    assert rules["value"]["min_odds"] == 1.80
    assert rules["value"]["min_edge"] == 0.05
    assert rules["value"]["min_expected_value"] == 0.08
    assert rules["value"]["limit"] is None
    assert rules["value"]["presentation_preview_limit"] == 10
    assert rules["doubles"]["model_branch"] == "separate"
    assert rules["match_winner_assignment"]["exclusive"] is True
    assert rules["match_winner_assignment"]["priority"] == ["prime", "top_daily", "value"]
    assert set(rules["ace"]["markets"]) == {"aces", "double_faults"}
    assert set(rules["sg"]["markets"]) == {"sets", "games"}
    assert rules["btts"]["href"] == "/btts"
    dashboard = cfg["dashboard"]
    assert dashboard["section_order"] == ["prime", "top_daily", "value", "doubles", "ace", "sg"]
    assert dashboard["visible_slots"] == 4
    assert dashboard["user_switches"] is True


def test_banner_adaptation_and_watermark_controls_are_exposed_in_admin():
    cfg = _cfg()
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert "mobile_image_url" in app_js
    assert "image_fit" in app_js
    assert "image_position" in app_js
    assert "data-admin-watermark" in app_js
    assert "COMING SOON" in app_js
    assert ".promo-image.fit-cover" in css
    assert ".promo-image.pos-center" in css
    assert cfg["elements"]["SIDEBAR_PROMO_2"]["watermark"]["text"] == "COMING SOON"


def test_public_sidebar_is_betting_first_and_admin_is_isolated_at_bottom():
    cfg = _cfg()
    nav_items = sorted(
        [item for item in cfg["elements"].values() if item.get("kind") == "navigation"],
        key=lambda item: item["order"],
    )
    nav = {item["content"]["route"]: item["content"]["label"] for item in nav_items}
    assert list(nav) == ["predictions", "prime", "top_daily", "value", "doubles", "ace", "sg", "results", "btts"]
    assert nav["prime"] == "Prime Picks"
    for removed in ("tournaments", "players", "stats", "model", "backtests", "account"):
        assert removed not in nav
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'id="adminNavigationWrap"' in html
    assert "['doubles','Doubles','◈']" in app
    assert "['btts','BTTS Bonus','⚽']" in app
    assert "renderAdminPerformance" in app
