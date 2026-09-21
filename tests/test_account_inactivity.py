from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tbt.services.account_inactivity as lifecycle


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def cfg():
    return SimpleNamespace(
        blinq_smtp_host="smtp.example.test",
        blinq_smtp_port=587,
        blinq_smtp_username="",
        blinq_smtp_password="",
        blinq_smtp_from="blinq@example.test",
        blinq_smtp_starttls=True,
        blinq_public_url="https://blinq.example.test",
        blinq_admin_emails="ops@example.test, owner@example.test",
        blinq_admin_email="owner@example.test",
    )


def rookie(days=23):
    return {
        "id": "u-rookie",
        "email": "rookie@example.test",
        "created_at": (NOW - timedelta(days=200)).isoformat(),
        "last_sign_in_at": (NOW - timedelta(days=days)).isoformat(),
        "app_metadata": {"blinq_plan": "rookie", "blinq_status": "active"},
        "user_metadata": {},
    }


def paid(days=7, plan="elite"):
    expiry = NOW + timedelta(days=days) - timedelta(hours=1)
    return {
        "id": f"u-{plan}",
        "email": f"{plan}@example.test",
        "created_at": (NOW - timedelta(days=100)).isoformat(),
        "last_sign_in_at": NOW.isoformat(),
        "app_metadata": {
            "blinq_plan": plan,
            "blinq_status": "active",
            "blinq_expires_at": expiry.isoformat(),
        },
        "user_metadata": {},
    }


def setup(monkeypatch, users, metas=None):
    metas = metas or {}
    monkeypatch.setattr(lifecycle, "list_users", lambda *_a, **_k: list(users))
    monkeypatch.setattr(lifecycle, "load_account_metadata", lambda uid: dict(metas.get(uid, {})))
    monkeypatch.setattr(lifecycle, "firebase_get_user", lambda _cfg, uid: next((u for u in users if u["id"] == uid), None))
    sent = []
    saved_inactivity = []
    saved_paid = []
    updates = []

    def send(_cfg, recipient, **kwargs):
        sent.append((recipient, kwargs))
        return True

    monkeypatch.setattr(lifecycle, "send_blinq_transactional_email", send)
    monkeypatch.setattr(lifecycle, "save_inactivity_state", lambda uid, **kw: saved_inactivity.append((uid, kw)) or {})
    monkeypatch.setattr(lifecycle, "save_subscription_notice_state", lambda uid, **kw: saved_paid.append((uid, kw)) or {})
    monkeypatch.setattr(lifecycle, "update_user_access", lambda _cfg, uid, payload, **kw: updates.append((uid, payload, kw)) or {})
    return sent, saved_inactivity, saved_paid, updates


def test_policy_defaults_to_final_30_day_lifecycle():
    policy = lifecycle.inactivity_policy({"account_inactivity": {}})
    assert policy == {
        "enabled": True,
        "inactive_days": 30,
        "warning_days": 7,
        "notify_admin": True,
        "notify_user": True,
        "auto_expire_rookie": True,
    }


def test_admin_recipients_support_plural_and_legacy_without_duplicates():
    assert lifecycle.admin_recipients(cfg()) == ["ops@example.test", "owner@example.test"]
    assert lifecycle.smtp_diagnostics(cfg())["admin_recipient_count"] == 2


def test_inactivity_warning_is_branded_and_persisted_immediately(monkeypatch):
    user = rookie(23)
    sent, markers, _, updates = setup(monkeypatch, [user])
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    user_mail = next(kwargs for recipient, kwargs in sent if recipient == user["email"])
    assert "28. 9. 2026" in user_mail["subject"]
    assert user_mail["eyebrow"] == "BLINQ ACCOUNT"
    assert "EXPIRED" in user_mail["body_sk"]
    assert result["warnings"] == 1
    assert result["expired"] == 0
    assert markers[0][1]["warning_status"] == "pending"
    assert markers[1][1]["warning_status"] == "sent"
    assert markers[1][1]["deactivation_warning_sent_at"] == NOW.isoformat()
    assert updates == []


def test_inactivity_expiry_uses_fixed_last_activity_deadline_and_rechecks_activity(monkeypatch):
    user = rookie(31)
    warning = NOW - timedelta(days=8)
    metas = {user["id"]: {
        "inactivity_warning_sent_at": warning.isoformat(),
        "inactivity_user_warning_sent_at": warning.isoformat(),
        "inactivity_deactivation_warning_sent_at": warning.isoformat(),
    }}
    sent, markers, _, updates = setup(monkeypatch, [user], metas)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["expired"] == 1
    assert updates[0][1]["status"] == "expired"
    assert any(item[1].get("expired_at") for item in markers)
    assert any(recipient == user["email"] and "EXPIRED" in kwargs["subject"] for recipient, kwargs in sent)


def test_late_warning_preserves_minimum_three_day_notice(monkeypatch):
    user = rookie(31)
    warning = NOW - timedelta(days=2)
    metas = {user["id"]: {
        "inactivity_warning_sent_at": warning.isoformat(),
        "inactivity_user_warning_sent_at": warning.isoformat(),
        "inactivity_deactivation_warning_sent_at": warning.isoformat(),
    }}
    _, _, _, updates = setup(monkeypatch, [user], metas)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["expired"] == 0
    assert updates == []


def test_recent_server_activity_blocks_expiry_even_if_firebase_login_is_old(monkeypatch):
    user = rookie(40)
    warning = NOW - timedelta(days=8)
    metas = {user["id"]: {
        "last_activity_at": (NOW - timedelta(hours=1)).isoformat(),
        "inactivity_warning_sent_at": warning.isoformat(),
        "inactivity_user_warning_sent_at": warning.isoformat(),
        "inactivity_deactivation_warning_sent_at": warning.isoformat(),
    }}
    sent, markers, _, updates = setup(monkeypatch, [user], metas)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["inactive"] == 0
    assert result["expired"] == 0
    assert updates == []
    assert markers == []


def test_paid_subscription_sends_7_day_notice_once_per_exact_expiry(monkeypatch):
    user = paid(7, "elite")
    sent, _, saved_paid, _ = setup(monkeypatch, [user])
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    mail = next(kwargs for recipient, kwargs in sent if recipient == user["email"])
    assert "7 dní" in mail["subject"]
    assert "ELITE" in mail["title_sk"]
    assert result["subscription_7"] == 1
    assert result["subscription_3"] == 0
    assert saved_paid[0][1]["status"] == "pending"
    assert saved_paid[1][1]["status"] == "sent"
    assert saved_paid[1][1]["days"] == 7


def test_paid_pending_notice_is_not_blindly_resent(monkeypatch):
    user = paid(7, "elite")
    expiry = user["app_metadata"]["blinq_expires_at"]
    sent, _, saved_paid, _ = setup(monkeypatch, [user], {user["id"]: {
        "subscription_expiry_7_for": expiry,
        "subscription_expiry_7_status": "pending",
    }})
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["subscription_7"] == 0
    assert saved_paid == []
    assert not any(recipient == user["email"] for recipient, _ in sent)


def test_paid_subscription_sends_3_day_notice_and_skips_existing_marker(monkeypatch):
    user = paid(3, "legend")
    expiry = user["app_metadata"]["blinq_expires_at"]
    sent, _, saved_paid, _ = setup(monkeypatch, [user], {user["id"]: {"subscription_expiry_3_for": expiry}})
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["subscription_3"] == 0
    assert saved_paid == []
    assert not any(recipient == user["email"] for recipient, _ in sent)


def test_admin_summary_goes_to_all_configured_admin_recipients(monkeypatch):
    user = paid(3, "pro")
    sent, _, _, _ = setup(monkeypatch, [user])
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    recipients = [recipient for recipient, _ in sent]
    assert "ops@example.test" in recipients
    assert "owner@example.test" in recipients
    assert result["admin_emails"] == 2
    assert result["admin_email"] is True


def test_paid_reminders_still_run_when_inactivity_housekeeping_is_disabled(monkeypatch):
    user = paid(7, "goat")
    sent, _, saved_paid, _ = setup(monkeypatch, [user])
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {"enabled": False}}, now=NOW)
    assert result["enabled"] is False
    assert result["subscription_7"] == 1
    assert saved_paid and saved_paid[0][1]["days"] == 7
    assert any(recipient == user["email"] for recipient, _ in sent)
