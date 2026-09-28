from pathlib import Path
import json

from tbt.services.account_inactivity import inactivity_policy
from tbt.services.admin_storage import validate_ui_config

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
APP = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
API = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "api" / "tbt" / "config.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "account-inactivity.yml").read_text(encoding="utf-8")


def test_r24_contract_survives_newer_release_patches():
    release_no = int(RELEASE["patch"].split("r", 1)[1])
    ui_no = int(UI["ui_patch"].split("r", 1)[1])
    assert release_no >= 24
    assert ui_no >= 24
    assert f'content="{RELEASE["patch"]}"' in INDEX


def test_rookie_is_permanent_free_base_tier():
    plans = UI["plans"]
    assert plans["trial"]["enabled"] is False
    assert plans["trial"]["trial_hours"] == 0
    assert plans["rookie"]["enabled"] is True
    assert plans["rookie"]["unlimited"] is True
    assert plans["rookie"]["duration_days"] is None
    assert validate_ui_config(UI)["plans"]["rookie"]["unlimited"] is True
    assert "ROOKIE is always the permanent free base tier" in APP
    assert "Bez časového obmedzenia" in APP


def test_membership_green_eyebrow_is_independently_editable_and_can_be_blank():
    for tier in ("rookie", "pro", "elite", "legend", "goat"):
        assert "eyebrow" in UI["plans"][tier]
    assert 'data-admin-level-field="eyebrow"' in APP
    assert "prázdne = skryť" in APP
    assert "function planEyebrowHtml(plan={})" in APP
    assert "const value=Object.prototype.hasOwnProperty.call(plan,'eyebrow')?String(plan.eyebrow??'').trim():'';" in APP
    assert "return value?`<small>${escapeHtml(value)}</small>`:'';" in APP


def test_inactivity_policy_uses_final_30_day_expired_housekeeping():
    policy = inactivity_policy(UI)
    assert policy == {
        "enabled": True,
        "inactive_days": 30,
        "warning_days": 7,
        "notify_admin": True,
        "notify_user": True,
        "auto_expire_rookie": True,
    }
    assert 'data-admin-inactivity-field="enabled"' in APP
    assert 'data-admin-inactivity-field="notify_admin"' in APP
    assert 'data-admin-inactivity-field="notify_user"' in APP
    assert 'data-admin-inactivity-field="auto_expire_rookie"' in APP


def test_daily_account_worker_and_smtp_diagnostics_are_wired():
    assert 'route="v1/internal/account-inactivity-worker"' in API
    assert "run_inactivity_review" in API
    assert "account_inactivity" in API
    assert "smtp_diagnostics" in API
    assert "BLINQ_ACCOUNT_WORKER_TOKEN" in CONFIG
    assert "BLINQ_SMTP_HOST" in CONFIG
    assert "BLINQ_ADMIN_EMAILS" in CONFIG
    assert "TBT_ACCOUNT_INACTIVITY_ENABLED" in WORKFLOW
    assert "BLINQ_ACCOUNT_WORKER_TOKEN" in WORKFLOW
    assert "/api/v1/internal/account-inactivity-worker" in WORKFLOW
    assert "ACCOUNT CHECK" in APP
    assert "EMAIL / SMTP" in APP
