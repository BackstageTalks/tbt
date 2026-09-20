from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tbt.services.account_inactivity as inactivity


NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def cfg():
    return SimpleNamespace(
        blinq_smtp_host="smtp.example.test",
        blinq_smtp_port=587,
        blinq_smtp_username="",
        blinq_smtp_password="",
        blinq_smtp_from="blinq@example.test",
        blinq_smtp_starttls=True,
        blinq_admin_email="admin@example.test",
    )


def dormant_user(days=100):
    return {
        "id": "u1",
        "email": "member@example.test",
        "created_at": (NOW - timedelta(days=200)).isoformat(),
        "last_sign_in_at": (NOW - timedelta(days=days)).isoformat(),
        "app_metadata": {},
        "user_metadata": {},
    }


def setup_worker(monkeypatch, user, meta=None):
    monkeypatch.setattr(inactivity, "list_users", lambda *_args, **_kwargs: [user])
    monkeypatch.setattr(inactivity, "load_account_metadata", lambda _uid: dict(meta or {}))
    mails = []
    markers = []
    updates = []
    monkeypatch.setattr(inactivity, "_send_mail", lambda _cfg, recipient, subject, body: mails.append((recipient, subject, body)) or True)
    monkeypatch.setattr(inactivity, "save_inactivity_state", lambda uid, **kwargs: markers.append((uid, kwargs)) or {})
    monkeypatch.setattr(inactivity, "update_user_access", lambda _cfg, uid, payload, **kwargs: updates.append((uid, payload, kwargs)) or {})
    return mails, markers, updates


def test_policy_defaults_to_seven_day_user_warning():
    policy = inactivity.inactivity_policy({"account_inactivity": {}})
    assert policy["warning_days"] == 7
    assert policy["notify_user"] is True
    assert policy["auto_expire_rookie"] is False


def test_dormant_rookie_only_notifies_admin_when_user_warning_is_explicitly_disabled(monkeypatch):
    user = dormant_user(100)
    mails, markers, updates = setup_worker(monkeypatch, user)
    result = inactivity.run_inactivity_review(cfg(), {
        "account_inactivity": {
            "enabled": True,
            "inactive_days": 90,
            "warning_days": 7,
            "notify_admin": True,
            "notify_user": False,
            "auto_expire_rookie": False,
        }
    }, now=NOW)
    assert result["warnings"] == 1
    assert result["expired"] == 0
    assert result["admin_email"] is True
    assert updates == []
    assert [mail[0] for mail in mails] == ["admin@example.test"]
    assert markers and markers[0][1].get("warning_sent_at")
    assert not markers[0][1].get("user_warning_sent_at")


def test_auto_expiry_forces_user_warning_and_never_uses_admin_only_marker(monkeypatch):
    user = dormant_user(100)
    # Legacy/admin-only warning marker must never authorize deactivation.
    meta = {"inactivity_warning_sent_at": (NOW - timedelta(days=8)).isoformat()}
    mails, markers, updates = setup_worker(monkeypatch, user, meta=meta)
    result = inactivity.run_inactivity_review(cfg(), {
        "account_inactivity": {
            "enabled": True,
            "inactive_days": 90,
            "warning_days": 7,
            "notify_admin": True,
            "notify_user": False,
            "auto_expire_rookie": True,
        }
    }, now=NOW)
    assert result["policy"]["notify_user"] is True
    assert result["expired"] == 0
    assert updates == []
    assert any(mail[0] == "member@example.test" for mail in mails)
    assert any(item[1].get("user_warning_sent_at") for item in markers)


def test_auto_expiry_waits_full_warning_period_after_actual_user_email(monkeypatch):
    user = dormant_user(100)
    meta = {
        "inactivity_warning_sent_at": (NOW - timedelta(days=3)).isoformat(),
        "inactivity_user_warning_sent_at": (NOW - timedelta(days=3)).isoformat(),
        "inactivity_deactivation_warning_sent_at": (NOW - timedelta(days=3)).isoformat(),
    }
    mails, markers, updates = setup_worker(monkeypatch, user, meta=meta)
    result = inactivity.run_inactivity_review(cfg(), {
        "account_inactivity": {
            "enabled": True,
            "inactive_days": 90,
            "warning_days": 7,
            "notify_admin": True,
            "notify_user": True,
            "auto_expire_rookie": True,
        }
    }, now=NOW)
    assert result["warnings"] == 0
    assert result["expired"] == 0
    assert updates == []



def test_old_generic_user_notice_does_not_authorize_later_deactivation(monkeypatch):
    user = dormant_user(100)
    meta = {
        "inactivity_warning_sent_at": (NOW - timedelta(days=10)).isoformat(),
        "inactivity_user_warning_sent_at": (NOW - timedelta(days=10)).isoformat(),
    }
    mails, markers, updates = setup_worker(monkeypatch, user, meta=meta)
    result = inactivity.run_inactivity_review(cfg(), {
        "account_inactivity": {
            "enabled": True,
            "inactive_days": 90,
            "warning_days": 7,
            "notify_admin": True,
            "notify_user": True,
            "auto_expire_rookie": True,
        }
    }, now=NOW)
    assert result["expired"] == 0
    assert updates == []
    assert any(mail[0] == "member@example.test" and "deaktivovaný" in mail[1] for mail in mails)
    assert any(item[1].get("deactivation_warning_sent_at") for item in markers)

def test_auto_expiry_can_run_after_seven_days_from_actual_user_warning(monkeypatch):
    user = dormant_user(100)
    meta = {
        "inactivity_warning_sent_at": (NOW - timedelta(days=8)).isoformat(),
        "inactivity_user_warning_sent_at": (NOW - timedelta(days=8)).isoformat(),
        "inactivity_deactivation_warning_sent_at": (NOW - timedelta(days=8)).isoformat(),
    }
    mails, markers, updates = setup_worker(monkeypatch, user, meta=meta)
    result = inactivity.run_inactivity_review(cfg(), {
        "account_inactivity": {
            "enabled": True,
            "inactive_days": 90,
            "warning_days": 7,
            "notify_admin": True,
            "notify_user": True,
            "auto_expire_rookie": True,
        }
    }, now=NOW)
    assert result["warnings"] == 0
    assert result["expired"] == 1
    assert len(updates) == 1
    assert updates[0][1]["plan"] == "rookie"
    assert updates[0][1]["status"] == "expired"
    assert any(item[1].get("expired_at") for item in markers)
    assert result["admin_email"] is True
    assert any(mail[0] == "member@example.test" and "deaktivovaný" in mail[2] for mail in mails)
