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
    monkeypatch.setattr(lifecycle, "record_account_event", lambda **_kwargs: None)
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



def test_expired_paid_plans_are_persistently_downgraded_and_push_is_synced(monkeypatch):
    for plan in ("pro", "elite", "legend", "goat"):
        account = paid(0, plan)
        sent, _, _, updates = setup(monkeypatch, [account])
        push = []
        monkeypatch.setattr(lifecycle, "sync_push_access", lambda **kw: push.append(kw))
        result = lifecycle.run_inactivity_review(
            cfg(), {"account_inactivity": {"enabled": False}}, now=NOW,
        )
        assert result["paid_downgraded"] == 1
        assert len(updates) == 1
        uid, changes, opts = updates[0]
        assert uid == account["id"]
        assert changes == {
            "role": "user", "plan": "rookie", "status": "active", "expires_at": None,
        }
        assert opts["actor_id"] == "account-lifecycle-worker"
        assert opts["expected_claims"]["blinq_plan"] == plan
        assert opts["expected_claims"]["blinq_expires_at"] == account["app_metadata"]["blinq_expires_at"]
        assert push == [{"user_id": uid, "plan": "rookie", "status": "active", "expires_at": None}]
        assert result["subscription_7"] == result["subscription_3"] == 0
        if plan in {"elite", "legend", "goat"}:
            admin_mail = next(kwargs for recipient, kwargs in sent if recipient == "ops@example.test")
            assert "Paid → ROOKIE" in admin_mail["body_sk"]
            assert "manual Telegram" not in admin_mail["body_sk"]


def test_paid_downgrade_emits_operator_queue_event(monkeypatch):
    account = paid(0, "elite")
    setup(monkeypatch, [account], {account["id"]: {"telegram_nick": "@member78"}})
    events = []
    monkeypatch.setattr(lifecycle, "record_account_event", lambda **kw: events.append(kw))
    monkeypatch.setattr(lifecycle, "sync_push_access", lambda **kw: None)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {"enabled": False}}, now=NOW)
    assert result["paid_downgraded"] == 1
    assert len(events) == 1
    assert events[0]["action"] == "paid_membership_downgraded"
    assert events[0]["after"]["telegram_nick"] == "@member78"
    assert events[0]["after"]["to_plan"] == "rookie"


def test_renewed_paid_membership_is_not_downgraded_from_stale_scan(monkeypatch):
    old = paid(0, "pro")
    renewed = {**old, "app_metadata": {
        **old["app_metadata"],
        "blinq_expires_at": (NOW + timedelta(days=30)).isoformat(),
    }}
    _, _, _, updates = setup(monkeypatch, [old])
    monkeypatch.setattr(lifecycle, "firebase_get_user", lambda _cfg, _uid: renewed)
    monkeypatch.setattr(lifecycle, "sync_push_access", lambda **_kw: None)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["paid_downgraded"] == 0
    assert updates == []


def test_claim_race_aborts_paid_downgrade_without_losing_access(monkeypatch):
    from tbt.services.admin_accounts import AccessConflict
    old = paid(0, "elite")
    _, _, _, _ = setup(monkeypatch, [old])
    writes = []
    def fail_changed_claims(*_args, **_kwargs):
        writes.append("attempted")
        raise AccessConflict("Renewed by admin")
    monkeypatch.setattr(lifecycle, "update_user_access", fail_changed_claims)
    monkeypatch.setattr(lifecycle, "sync_push_access", lambda **_kw: writes.append("push"))
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert writes == ["attempted"]
    assert result["paid_downgraded"] == 0
    assert result["mail_failures"] == 0


def test_paid_downgrade_runs_without_smtp_or_inactivity_worker_policy(monkeypatch):
    old = paid(0, "legend")
    _, _, _, updates = setup(monkeypatch, [old])
    monkeypatch.setattr(lifecycle, "sync_push_access", lambda **_kw: None)
    no_smtp = cfg()
    no_smtp.blinq_smtp_host = ""
    result = lifecycle.run_inactivity_review(
        no_smtp, {"account_inactivity": {"enabled": False}}, now=NOW,
    )
    assert result["smtp_configured"] is False
    assert result["enabled"] is False
    assert result["paid_downgraded"] == 1
    assert updates[0][1]["plan"] == "rookie"


def test_smtp_diagnostics_reports_sender_domain_without_secrets():
    settings = cfg()
    settings.blinq_smtp_username = "smtp-credential@example.test"
    settings.blinq_smtp_password = "never-show-this-password"
    settings.blinq_smtp_from = "BlinQ <accounts@example.test>"
    info = lifecycle.smtp_diagnostics(settings)
    assert info["sender_domain"] == "example.test"
    assert info["smtp_host"] == "smtp.example.test"
    assert info["smtp_auth_configured"] is True
    assert info["tls_mode"] == "starttls"
    assert info["authentication_results"] == "not_verified"
    assert "smtp-credential@example.test" not in str(info)
    assert "never-show-this-password" not in str(info)
    assert "accounts@example.test" not in str(info)


def test_smtp_diagnostics_flags_unencrypted_transport_without_claiming_authentication():
    settings = cfg()
    settings.blinq_smtp_starttls = False
    info = lifecycle.smtp_diagnostics(settings)
    assert info["tls_mode"] == "unencrypted"
    assert info["authentication_results"] == "not_verified"
    settings.blinq_smtp_port = 465
    assert lifecycle.smtp_diagnostics(settings)["tls_mode"] == "implicit_tls"

def test_paid_notice_scheduled_event_precedes_transport(monkeypatch):
    user = paid(7, "elite")
    setup(monkeypatch, [user])
    activity = []
    monkeypatch.setattr(lifecycle, "record_account_event", lambda **kwargs: activity.append(kwargs))
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    pending = [row for row in activity if row["action"] == "account_email_delivery"]
    assert [entry["outcome"] for entry in pending] == ["pending", "sent"]
    assert all(entry["target_id"] == user["id"] for entry in pending)
    assert "7 dní" in pending[0]["after"]["subject"]
    assert result["subscription_7"] == 1


def test_recent_paid_to_rookie_transition_starts_new_inactivity_cycle(monkeypatch):
    # The member did not log in during paid membership; an earlier 30-day
    # warning must not be reused after the access writer switched the tier.
    user = rookie(200)
    meta = {
        "access_metadata_updated_at": (NOW - timedelta(days=1)).isoformat(),
        "inactivity_deactivation_warning_sent_at": (NOW - timedelta(days=30)).isoformat(),
        "inactivity_warning_status": "sent",
    }
    sent, saved, _, updates = setup(monkeypatch, [user], {user["id"]: meta})
    summary = lifecycle.run_inactivity_review(
        cfg(), {"account_inactivity": {"inactive_days": 30, "warning_days": 7}},
        now=NOW,
    )
    assert summary["inactive"] == summary["warnings"] == summary["expired"] == 0
    assert saved == []
    assert updates == []
    assert not any(recipient == user["email"] for recipient, _ in sent)


def test_rookie_inactivity_uses_latest_access_change_or_actual_activity(monkeypatch):
    user = rookie(200)
    access_change = NOW - timedelta(days=23)
    meta = {
        "access_metadata_updated_at": access_change.isoformat(),
        "last_activity_at": (NOW - timedelta(days=50)).isoformat(),
        "inactivity_deactivation_warning_sent_at": (NOW - timedelta(days=100)).isoformat(),
    }
    sent, _, _, updates = setup(monkeypatch, [user], {user["id"]: meta})
    summary = lifecycle.run_inactivity_review(
        cfg(), {"account_inactivity": {"inactive_days": 30, "warning_days": 7}},
        now=NOW,
    )
    assert summary["warnings"] == 1
    assert summary["expired"] == 0
    assert updates == []
    assert sum(recipient == user["email"] for recipient, _ in sent) == 1
    # A later real login takes priority over the transition timestamp.
    user["last_sign_in_at"] = (NOW - timedelta(days=2)).isoformat()
    assert lifecycle._last_seen(user, meta) == NOW - timedelta(days=2)


def test_inactivity_smtp_rejection_is_audited_and_retryable(monkeypatch):
    user = rookie(23)
    setup(monkeypatch, [user])
    activity = []
    markers = []
    monkeypatch.setattr(lifecycle, "record_account_event", lambda **kw: activity.append(kw))
    monkeypatch.setattr(lifecycle, "save_inactivity_state", lambda uid, **kw: markers.append((uid, kw)) or {})
    monkeypatch.setattr(lifecycle, "send_blinq_transactional_email", lambda *_a, **_kw: False)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["warnings"] == 0
    assert result["mail_failures"] == 1
    assert [e["outcome"] for e in activity] == ["pending", "failed"]
    assert [state["warning_status"] for _, state in markers] == ["pending", "failed"]


def test_inactivity_uncertain_smtp_exception_keeps_pending_to_prevent_spam(monkeypatch):
    user = rookie(23)
    setup(monkeypatch, [user])
    activity = []
    markers = []
    monkeypatch.setattr(lifecycle, "record_account_event", lambda **kw: activity.append(kw))
    monkeypatch.setattr(lifecycle, "save_inactivity_state", lambda uid, **kw: markers.append((uid, kw)) or {})
    def lost_smtp_response(*_a, **_kw):
        raise RuntimeError("SMTP response ambiguous")
    monkeypatch.setattr(lifecycle, "send_blinq_transactional_email", lost_smtp_response)
    result = lifecycle.run_inactivity_review(cfg(), {"account_inactivity": {}}, now=NOW)
    assert result["warnings"] == 0
    assert result["mail_failures"] == 1
    assert [e["outcome"] for e in activity] == ["pending"]
    assert [state["warning_status"] for _, state in markers] == ["pending"]


def test_paid_tiers_never_receive_inactivity_warnings_for_old_logins(monkeypatch):
    """Only active ROOKIE members are subject to inactivity, regardless of login age."""
    for plan in ("pro", "elite", "legend", "goat"):
        account = paid(45, plan)
        account["last_sign_in_at"] = (NOW - timedelta(days=250)).isoformat()
        account["created_at"] = (NOW - timedelta(days=300)).isoformat()
        historical_rookie_warning = (NOW - timedelta(days=200)).isoformat()
        sent, inactivity_writes, paid_writes, access_writes = setup(
            monkeypatch,
            [account],
            {account["id"]: {
                "last_activity_at": (NOW - timedelta(days=250)).isoformat(),
                "inactivity_deactivation_warning_sent_at": historical_rookie_warning,
                "inactivity_warning_for": (NOW - timedelta(days=250)).isoformat(),
                "inactivity_warning_status": "sent",
            }},
        )
        summary = lifecycle.run_inactivity_review(
            cfg(), {"account_inactivity": {"enabled": True, "inactive_days": 30, "warning_days": 7}},
            now=NOW,
        )
        assert summary["inactive"] == summary["warnings"] == summary["expired"] == 0, plan
        assert summary["paid_downgraded"] == 0, plan
        assert inactivity_writes == access_writes == paid_writes == [], plan
        assert not any(recipient == account["email"] for recipient, _ in sent), plan


def test_paid_expiry_reminders_are_not_inactivity_notices(monkeypatch):
    """An old paid login must not suppress legitimate 7/3-day membership-expiry emails."""
    for plan, days in (("pro", 7), ("elite", 3), ("legend", 7), ("goat", 3)):
        account = paid(days, plan)
        account["last_sign_in_at"] = (NOW - timedelta(days=250)).isoformat()
        sent, inactivity_writes, paid_writes, access_writes = setup(monkeypatch, [account])
        summary = lifecycle.run_inactivity_review(
            cfg(), {"account_inactivity": {"enabled": True, "inactive_days": 30, "warning_days": 7}},
            now=NOW,
        )
        assert summary["inactive"] == summary["warnings"] == summary["expired"] == 0, plan
        assert summary[f"subscription_{days}"] == 1, plan
        assert len(paid_writes) == 2, plan
        assert inactivity_writes == access_writes == [], plan
        recipient_mails = [mail for recipient, mail in sent if recipient == account["email"]]
        assert len(recipient_mails) == 1, plan
        assert f"{days} dní" in recipient_mails[0]["subject"], plan
        assert "neaktivitu" not in recipient_mails[0]["subject"].lower(), plan


def test_downgrade_never_triggers_same_run_inactivity_even_after_long_paid_absence(monkeypatch):
    """A just-ended paid plan is downgraded once, without mailing or expiring ROOKIE."""
    for plan in ("pro", "elite", "legend", "goat"):
        account = paid(0, plan)
        account["last_sign_in_at"] = (NOW - timedelta(days=250)).isoformat()
        account["created_at"] = (NOW - timedelta(days=300)).isoformat()
        sent, inactivity_writes, paid_writes, access_writes = setup(monkeypatch, [account])
        monkeypatch.setattr(lifecycle, "sync_push_access", lambda **_kwargs: None)
        summary = lifecycle.run_inactivity_review(
            cfg(), {"account_inactivity": {"enabled": True, "inactive_days": 30, "warning_days": 7}},
            now=NOW,
        )
        assert summary["paid_downgraded"] == 1, plan
        assert summary["inactive"] == summary["warnings"] == summary["expired"] == 0, plan
        assert inactivity_writes == paid_writes == [], plan
        assert len(access_writes) == 1 and access_writes[0][1]["plan"] == "rookie", plan
        assert access_writes[0][1]["status"] == "active", plan
        assert not any(recipient == account["email"] for recipient, _ in sent), plan
