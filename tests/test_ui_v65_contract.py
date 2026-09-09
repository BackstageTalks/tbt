import copy
import json
from pathlib import Path

import pytest

from tbt.services.admin_storage import validate_ui_config
from tbt.services.feed import empty_feed

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_v65_four_window_order_is_single_consistent_contract():
    cfg = _cfg()
    expected = ["prime", "top_daily", "value", "doubles", "ace", "sg"]
    assert tuple(map(int, cfg["ui_revision"].split("."))) >= (6, 5, 4)
    assert cfg["dashboard"]["section_order"] == expected
    assert cfg["dashboard"]["visible_slots"] == 4
    assert cfg["dashboard"]["user_switches"] is False
    assert cfg["dashboard"]["show_disabled_strip"] is False
    assert cfg["dashboard"]["auto_replace_empty_sections"] is True
    assert cfg["dashboard"]["cards_per_panel_desktop"] == 2
    assert cfg["dashboard"]["cards_per_panel_wide"] == 3
    assert [k for k in expected if cfg["dashboard"]["sections"][k]["dashboard_enabled"]] == ["prime", "top_daily", "value", "ace"]
    assert cfg["dashboard"]["sections"]["results"]["dashboard_enabled"] is False
    assert cfg["dashboard"]["sections"]["btts"]["dashboard_enabled"] is False
    assert validate_ui_config(cfg) is cfg


def test_v65_sidebar_and_runtime_order_match_dashboard_order():
    cfg = _cfg()
    nav_items = sorted(
        [item for item in cfg["elements"].values() if item.get("kind") == "navigation"],
        key=lambda item: item["order"],
    )
    assert [item["content"]["route"] for item in nav_items] == [
        "predictions", "prime", "top_daily", "value", "doubles", "ace", "sg", "results", "btts"
    ]
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "const dashboardPickSectionKeys=['prime','top_daily','value','doubles','ace','sg'];" in app
    assert "['value','Value Picks','◇'],['doubles','Doubles','◈'],['ace','Ace Picks','♠']" in app


def test_v65_dashboard_admin_display_controls_results_tables_and_future_doubles_feed_are_present():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'id="dashboardSectionToggles"' in html
    assert 'id="dashboardSectionSwitcher" aria-label="Dashboard section visibility" hidden' in html
    assert 'data-dashboard-global-field="cards_per_panel_desktop"' in app
    assert 'data-dashboard-global-field="auto_replace_empty_sections"' in app
    assert 'id="headerFeatureStrip"' in html
    assert 'id="headerTime"' in html and 'id="headerDate"' in html
    assert "['pro','PRO','Unlock the full daily board'" in app
    assert "['elite','ELITE','Advanced match intelligence'" in app
    assert "['legend','LEGEND','Maximum BlinQ access'" in app
    assert 'id="dashboardDisabledSections"' in html
    assert 'id="doublesGrid"' in html
    assert 'data-route="results"' in html
    assert "renderResultsFilters()+resultsSummary()" in app
    assert "genericTable(marketRows('doubles'),'doubles')" in app
    assert "doubles:'Doubles'" in app
    assert "const useImage=preference==='image'&&images.length;" in app
    assert "route==='tournaments'" in app and "else if(route==='tournaments')" in app
    assert "doubles_picks" in empty_feed()


def test_v65_membership_terms_and_ad_fallback_are_locked_to_approved_policy():
    cfg = _cfg()
    plans = cfg["plans"]
    assert [plans[p]["order"] for p in ("rookie", "pro", "elite", "legend", "goat")] == [1, 2, 3, 4, 5]
    assert plans["elite"]["duration_days"] == 180
    assert plans["legend"]["duration_days"] == 365 and plans["legend"]["enabled"] is True
    assert plans["goat"]["lifetime"] is True
    assert all(plans[p]["hide_ads_allowed"] is False for p in ("rookie", "pro", "elite", "legend", "goat"))
    assert cfg["ad_fallbacks"]["priority"] == ["active_advertisement", "rss_news", "blinq_internal"]


def test_v65_top_bets_uses_two_point_daily_fill_without_lowering_hard_floor():
    rules = _cfg()["market_rules"]["top_daily"]
    assert rules["target_count"] == 10
    assert rules["confidence_tiers"] == [0.80, 0.78, 0.76, 0.74, 0.72, 0.70, 0.68]
    assert rules["min_probability"] == 0.68


def test_v65_runtime_config_validation_rejects_order_drift_and_plan_ad_free():
    cfg = _cfg()
    wrong_order = copy.deepcopy(cfg)
    wrong_order["dashboard"]["section_order"] = ["prime", "top_daily", "value", "ace", "doubles", "sg"]
    with pytest.raises(ValueError, match="section order"):
        validate_ui_config(wrong_order)

    ad_free = copy.deepcopy(cfg)
    ad_free["plans"]["goat"]["hide_ads_allowed"] = True
    with pytest.raises(ValueError, match="ad-free"):
        validate_ui_config(ad_free)
