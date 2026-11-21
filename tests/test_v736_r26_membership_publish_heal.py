from copy import deepcopy
import json
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config, resolve_ui_access_config

ROOT = Path(__file__).resolve().parents[1]
UI = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_publish_heals_stale_rookie_values_instead_of_rejecting():
    payload = deepcopy(UI)
    payload["plans"]["rookie"].update({
        "enabled": False,
        "duration_days": 30,
        "unlimited": False,
        "lifetime": True,
    })
    payload["plans"]["trial"].update({
        "enabled": True,
        "trial_hours": 72,
        "duration_days": 3,
    })
    saved = validate_ui_config(payload)
    rookie = saved["plans"]["rookie"]
    assert rookie["enabled"] is True
    assert rookie["duration_days"] is None
    assert rookie["unlimited"] is True
    assert rookie["lifetime"] is False
    trial = saved["plans"]["trial"]
    assert trial["enabled"] is False
    assert trial["trial_hours"] == 0
    assert trial["duration_days"] is None


def test_publish_heals_legacy_lifetime_goat_to_finite_default():
    payload = deepcopy(UI)
    payload["plans"]["goat"].update({
        "duration_days": None,
        "unlimited": True,
        "lifetime": True,
    })
    saved = validate_ui_config(payload)
    goat = saved["plans"]["goat"]
    assert goat["duration_days"] == 365
    assert goat["unlimited"] is False
    assert goat["lifetime"] is False


def test_locked_and_hidden_tier_panels_cannot_claim_full_offer():
    payload = deepcopy(UI)
    tabs = payload["dashboard"]["daily_hub"]["tabs"]
    scenarios = {
        ("double_faults", "elite"): "blurred",
        ("sets", "legend"): "blurred",
        ("doubles", "legend"): "hidden",
    }
    for (tab, plan), state in scenarios.items():
        rule = tabs[tab]["plans"][plan]
        rule.update({"display_state": state, "tab_enabled": state != "hidden",
                     "see_all": True, "visible_rows": 0})
    # An actually open panel may retain see_all; the change is strictly scoped.
    open_panel = tabs["ace"]["plans"]["legend"]
    open_panel.update({"display_state": "active", "tab_enabled": True,
                       "see_all": True, "visible_rows": "ALL"})

    effective = resolve_ui_access_config(deepcopy(payload))
    for (tab, plan), state in scenarios.items():
        rule = effective["dashboard"]["daily_hub"]["tabs"][tab]["plans"][plan]
        assert rule["display_state"] == state
        assert rule["visible_rows"] == 0
        assert rule["see_all"] is False
    assert effective["dashboard"]["daily_hub"]["tabs"]["ace"]["plans"]["legend"]["see_all"] is True

    saved = validate_ui_config(deepcopy(payload))
    for tab, plan in scenarios:
        assert saved["dashboard"]["daily_hub"]["tabs"][tab]["plans"][plan]["see_all"] is False


def test_admin_lock_selector_auto_clears_full_offer_in_browser_draft():
    source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "if(['blurred','hidden'].includes(String(rule.display_state||'')))rule.see_all=false;" in source
