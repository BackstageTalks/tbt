from pathlib import Path
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from tbt.services.admin_storage import validate_ui_config
from tbt.services.admin_accounts import normalize_access_update
from tbt.services.auth import account_access

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
APP = (WEB / "app.js").read_text(encoding="utf-8")


def _cfg():
    return {"admin_user_ids": [], "admin_emails": []}


def _user(meta):
    return {"id": "u1", "email": "member@example.com", "app_metadata": meta, "user_metadata": {}}


def test_r25_release_and_cache_identity():
    assert RELEASE["patch"] == "736-r31"
    assert UI["ui_patch"] == "736-r31"
    assert 'content="736-r31"' in INDEX
    for asset in ("blinq-app.css", "auth.js", "responsive.js", "app.js"):
        assert f"/{asset}?v=7360&p=31" in INDEX


def test_stale_hero_access_is_migrated_instead_of_blocking_publish():
    stale = copy.deepcopy(UI)
    hero = stale["elements"]["HERO_BANNER_1"]
    hero["access"] = {"trial":"active","expired":"hidden","rookie":"active","pro":"active","elite":"active","legend":"active","goat":"active"}
    hero["click_access"] = {"rookie": True}
    cleaned = validate_ui_config(stale)
    assert cleaned is stale
    assert "access" not in cleaned["elements"]["HERO_BANNER_1"]
    assert "click_access" not in cleaned["elements"]["HERO_BANNER_1"]
    assert "applyV6514AdminCleanup();\n      const result=await BlinqAuth.adminSaveUiConfig(state.ui);" in APP


def test_goat_is_finite_and_admin_editable():
    goat = UI["plans"]["goat"]
    assert goat["lifetime"] is False
    assert goat["unlimited"] is False
    assert goat["duration_days"] == 365
    cleaned = validate_ui_config(UI)
    assert cleaned["plans"]["goat"]["duration_days"] == 365
    assert "id==='goat'?'Doživotný level'" not in APP
    assert "selectedPlan==='goat'||selectedPlan==='rookie'" not in APP
    assert "planId==='goat'" not in APP[APP.index('function adminDefaultPlanDays'):APP.index('function decorateAdminMediaUploads')]


def test_old_lifetime_goat_ui_payload_migrates_to_finite_default():
    stale = copy.deepcopy(UI)
    stale["plans"]["goat"]["lifetime"] = True
    stale["plans"]["goat"]["duration_days"] = None
    cleaned = validate_ui_config(stale)
    assert cleaned["plans"]["goat"]["lifetime"] is False
    assert cleaned["plans"]["goat"]["duration_days"] == 365


def test_active_goat_requires_and_accepts_expiry():
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    expiry = (now + timedelta(days=90)).isoformat()
    normalized = normalize_access_update({"role":"user","plan":"goat","status":"active","expires_at":expiry})
    assert normalized["status"] == "active"
    assert normalized["expires_at"] == expiry
    access = account_access(_user({"blinq_plan":"goat","blinq_status":"active","blinq_expires_at":expiry}), cfg=_cfg(), now=now)
    assert access["plan"] == "goat"
    assert access["status"] == "active"
    assert access["expires_at"] == expiry


def test_new_lifetime_assignment_is_rejected_but_legacy_runtime_is_grandfathered():
    with pytest.raises(ValueError, match="no longer assignable"):
        normalize_access_update({"role":"user","plan":"goat","status":"lifetime"})
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    access = account_access(_user({"blinq_plan":"goat","blinq_status":"lifetime"}), cfg=_cfg(), now=now)
    assert access["plan"] == "goat"
    assert access["status"] == "lifetime"
