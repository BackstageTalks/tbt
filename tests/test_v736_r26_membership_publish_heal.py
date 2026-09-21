from copy import deepcopy
import json
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config

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
