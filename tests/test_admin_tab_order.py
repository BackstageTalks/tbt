"""Ordering controls keep their input safe and preserve all public prediction tabs."""
import copy
import json
from pathlib import Path

import pytest

from tbt.services.admin_storage import validate_ui_config


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ["daily", "prime", "value", "ace", "double_faults", "doubles", "games", "sets", "see_all"]


def config():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_tab_order_default_is_complete_and_valid():
    cfg = config()
    assert cfg["dashboard"]["daily_hub"]["tab_order"] == EXPECTED
    assert validate_ui_config(cfg)["dashboard"]["daily_hub"]["tab_order"] == EXPECTED


def test_tab_order_can_be_arbitrary_permutation():
    cfg = config()
    new_order = list(reversed(EXPECTED))
    cfg["dashboard"]["daily_hub"]["tab_order"] = new_order
    assert validate_ui_config(cfg)["dashboard"]["daily_hub"]["tab_order"] == new_order


@pytest.mark.parametrize("bad", [
    [], EXPECTED[:-1], EXPECTED + ["daily"], EXPECTED[:-1] + ["unknown"],
    "daily,prime,value", 123, [None] + EXPECTED[1:],
])
def test_invalid_tab_order_is_rejected(bad):
    cfg = config()
    cfg["dashboard"]["daily_hub"]["tab_order"] = copy.deepcopy(bad)
    with pytest.raises(ValueError, match="Invalid Daily Picks tab order"):
        validate_ui_config(cfg)


def test_legacy_config_without_tab_order_remains_supported():
    cfg = config()
    cfg["dashboard"]["daily_hub"].pop("tab_order")
    assert "tab_order" not in validate_ui_config(cfg)["dashboard"]["daily_hub"]


def test_admin_controls_and_mobile_nav_avoid_clipped_scroll_strip():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
    for needle in (
        "function orderedDailyHubTabs()",
        "const tabs=orderedDailyHubTabs()",
        "data-admin-hub-order-step",
        "data-admin-nav-edit",
        "data-admin-nav-step",
        "host.ondrop=event",
    ):
        assert needle in app
    assert ".admin-nav-group{grid-template-columns:repeat(2,minmax(0,1fr))!important}" in css
    assert "overflow:visible!important" in css
