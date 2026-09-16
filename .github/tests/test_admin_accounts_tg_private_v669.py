from types import SimpleNamespace

import pytest

from tbt.services import account_storage
from tbt.services.admin_accounts import tg_private_state
from tbt.services.auth import public_account


def _user(plan="elite", status="active", expires_at="2026-10-14T10:00:00+00:00"):
    claims = {"blinq_plan": plan, "blinq_status": status}
    if expires_at is not None:
        claims["blinq_expires_at"] = expires_at
    return {
        "id": "u1",
        "email": "member@example.com",
        "email_verified": True,
        "created_at": "2026-09-01T10:00:00+00:00",
        "last_sign_in_at": "2026-09-14T08:00:00+00:00",
        "user_metadata": {},
        "app_metadata": claims,
    }


def test_admin_metadata_validation_is_manual_and_boolean():
    assert account_storage.normalize_admin_metadata_update({
        "tg_private_member": True,
        "admin_note": "TG paired manually",
    }) == {"tg_private_member": True, "admin_note": "TG paired manually"}
    with pytest.raises(ValueError, match="true or false"):
        account_storage.normalize_admin_metadata_update({"tg_private_member": "yes"})


def test_admin_account_row_marks_elite_plus_for_add():
    profile = {"telegram_nick": "@elite_user", "tg_private_member": False, "admin_note": ""}
    row = tg_private_state(public_account(_user(), profile=profile), profile)
    assert row["tg_private_eligible"] is True
    assert row["tg_private_action"] == "add"


def test_admin_account_row_marks_downgraded_member_for_remove():
    profile = {"telegram_nick": "@former_elite", "tg_private_member": True, "admin_note": ""}
    row = tg_private_state(public_account(_user(plan="pro"), profile=profile), profile)
    assert row["tg_private_eligible"] is False
    assert row["tg_private_action"] == "remove"


def test_admin_account_row_marks_expired_elite_member_for_remove():
    profile = {"telegram_nick": "@expired_elite", "tg_private_member": True, "admin_note": ""}
    row = tg_private_state(public_account(_user(status="expired", expires_at="2026-09-01T10:00:00+00:00"), profile=profile), profile)
    assert row["tg_private_eligible"] is False
    assert row["tg_private_action"] == "remove"


def test_admin_account_row_marks_valid_group_member_ok():
    profile = {"telegram_nick": "@legend_user", "tg_private_member": True, "admin_note": "manual payment"}
    row = tg_private_state(public_account(_user(plan="legend"), profile=profile), profile)
    assert row["tg_private_eligible"] is True
    assert row["tg_private_action"] == "ok"


def test_frontend_account_manager_keeps_only_simple_filters_and_profile_editing():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    app = (root / "web/app.js").read_text(encoding="utf-8")
    html = (root / "web/index.html").read_text(encoding="utf-8")
    assert "adminUserLevelFilter" in app
    assert "adminUserStatusFilter" in app
    assert "adminUserSearch" in app
    assert "adminUserEmail" in app and "adminUserTelegram" in app
    start=app.index("function renderAdminUserEditor")
    end=app.index("function renderAdminAccounts", start)
    editor=app[start:end]
    assert "TG Private" not in editor
    assert "Manuálne spárovanie platby" not in editor
    assert "Telegram nickname" in html
    assert "Zobrazované meno" not in html

