from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tbt.services.auth import account_access, public_account
from tbt.services.admin_accounts import _apply_access_metadata, normalize_access_update


NOW = datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc)


def user(**overrides):
    payload = {
        "id": "u1",
        "email": "member@example.com",
        "created_at": (NOW - timedelta(hours=24)).isoformat(),
        "user_metadata": {"display_name": "Member"},
        "app_metadata": {},
    }
    payload.update(overrides)
    return payload


def cfg(**overrides):
    data = {
        "firebase_project_id": "blinq-182",
        "firebase_client_email": "server@example.iam.gserviceaccount.com",
        "firebase_private_key": "dummy",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_new_account_gets_unlimited_free_rookie_without_stored_plan():
    access = account_access(user(), cfg=cfg(), now=NOW)
    assert access["plan"] == "rookie"
    assert access["plan_label"] == "Rookie"
    assert access["status"] == "active"
    assert access["expires_at"] is None
    assert access["trial_expires_at"] is None


def test_old_unpaid_account_stays_active_rookie_without_expiry():
    access = account_access(
        user(created_at=(NOW - timedelta(days=400)).isoformat()),
        cfg=cfg(),
        now=NOW,
    )
    assert access["plan"] == "rookie"
    assert access["status"] == "active"
    assert access["expires_at"] is None


def test_legacy_rookie_expiry_is_ignored_when_status_is_active():
    access = account_access(
        user(app_metadata={
            "blinq_plan": "rookie",
            "blinq_status": "active",
            "blinq_expires_at": (NOW - timedelta(days=1)).isoformat(),
        }),
        cfg=cfg(),
        now=NOW,
    )
    assert access["plan"] == "rookie"
    assert access["status"] == "active"
    assert access["expires_at"] is None


def test_explicitly_archived_rookie_can_remain_expired():
    access = account_access(
        user(app_metadata={"blinq_plan": "rookie", "blinq_status": "expired"}),
        cfg=cfg(),
        now=NOW,
    )
    assert access["plan"] == "rookie"
    assert access["status"] == "expired"
    assert access["expires_at"] is None

def test_paid_plan_comes_only_from_app_metadata():
    access = account_access(
        user(app_metadata={
            "blinq_plan": "pro",
            "blinq_status": "active",
            "blinq_expires_at": (NOW + timedelta(days=30)).isoformat(),
        }),
        cfg=cfg(),
        now=NOW,
    )
    assert access["plan"] == "pro"
    assert access["status"] == "active"


def test_active_non_lifetime_plan_without_expiry_is_not_unlimited():
    access = account_access(
        user(app_metadata={"blinq_plan": "elite", "blinq_status": "active"}),
        cfg=cfg(),
        now=NOW,
    )
    assert access["plan"] == "elite"
    assert access["status"] == "expired"


def test_plan_based_hide_ads_is_disabled_for_all_membership_levels():
    for plan, days, status in (
        ("pro", 30, "active"),
        ("elite", 180, "active"),
        ("legend", 365, "active"),
        ("goat", 365, "active"),
    ):
        app_metadata = {"blinq_plan": plan, "blinq_status": status}
        if days is not None:
            app_metadata["blinq_expires_at"] = (NOW + timedelta(days=days)).isoformat()
        account = public_account(
            user(
                user_metadata={"display_name": "Member", "blinq_hide_ads": True},
                app_metadata=app_metadata,
            ),
            cfg=cfg(),
            now=NOW,
        )
        assert account["hide_ads_allowed"] is False
        assert account["hide_ads"] is False


def test_admin_role_is_separate_from_subscription_plan():
    account = public_account(
        user(app_metadata={"role": "admin", "blinq_plan": "rookie"}),
        cfg=cfg(),
        now=NOW,
    )
    assert account["role"] == "admin"
    assert account["plan"] == "admin"
    assert account["is_admin"] is True


def test_lifetime_is_no_longer_assignable_from_admin():
    with pytest.raises(ValueError, match="no longer assignable"):
        normalize_access_update({"role": "user", "plan": "goat", "status": "lifetime"})


def test_active_plan_requires_expiration_date():
    with pytest.raises(ValueError, match="expiration"):
        normalize_access_update({"role": "user", "plan": "pro", "status": "active"})


def test_active_rookie_does_not_require_expiration_date():
    normalized = normalize_access_update({"role": "user", "plan": "rookie", "status": "active"})
    assert normalized["status"] == "active"
    assert normalized["plan"] == "rookie"
    assert normalized["expires_at"] is None


def test_admin_update_keeps_claims_authorization_only():
    changes = normalize_access_update({
        "role": "user",
        "plan": "elite",
        "status": "active",
        "expires_at": (NOW + timedelta(days=365)).isoformat(),
        "payment_reference": "manual-link-payment-42",
    })
    app = _apply_access_metadata({
        "provider": "email",
        "role": "user",
        "blinq_payment_reference": "legacy-secret",
        "blinq_access_updated_by": "legacy-admin",
    }, changes)
    assert app["provider"] == "email"
    assert app["blinq_plan"] == "elite"
    assert app["blinq_status"] == "active"
    assert "blinq_payment_reference" not in app
    assert "blinq_access_updated_by" not in app


def test_admin_access_update_can_be_active_without_subscription_plan():
    normalized = normalize_access_update({"role": "admin", "plan": "", "status": "active"})
    assert normalized["role"] == "admin"
    assert normalized["plan"] == ""
    assert normalized["status"] == "active"


def test_avatar_variant_is_separate_profile_metadata_only():
    account = public_account(user(), cfg=cfg(), now=NOW, profile={"avatar_variant": "w"})
    invalid = public_account(user(), cfg=cfg(), now=NOW, profile={"avatar_variant": "other"})
    assert account["avatar_variant"] == "w"
    assert invalid["avatar_variant"] == ""


def test_suspension_overrides_admin_claim():
    access = account_access(
        user(app_metadata={"role": "admin", "blinq_status": "suspended"}),
        cfg=cfg(), now=NOW,
    )
    assert access["status"] == "suspended"
    assert access["is_admin"] is False
    assert access["role"] == "user"


@pytest.mark.parametrize("plan", ["pro", "elite", "legend", "goat"])
def test_paid_expiry_becomes_active_rookie_at_exact_deadline(plan):
    expiry = NOW.isoformat()
    member = user(app_metadata={
        "blinq_plan": plan,
        "blinq_status": "active",
        "blinq_expires_at": expiry,
    })
    before = account_access(member, now=NOW - timedelta(seconds=1))
    at_deadline = account_access(member, now=NOW)
    assert before["plan"] == plan
    assert before["status"] == "active"
    assert at_deadline["plan"] == "rookie"
    assert at_deadline["status"] == "active"
    assert at_deadline["expires_at"] is None
    assert at_deadline["is_admin"] is False
    assert public_account(member, now=NOW)["plan"] == "rookie"


@pytest.mark.parametrize("status", ["active", "expired"])
def test_elapsed_paid_memberships_recover_but_early_revocation_does_not(status):
    member = user(app_metadata={
        "blinq_plan": "elite",
        "blinq_status": status,
        "blinq_expires_at": (NOW - timedelta(days=1)).isoformat(),
    })
    assert account_access(member, now=NOW)["plan"] == "rookie"
    member["app_metadata"]["blinq_expires_at"] = (NOW + timedelta(days=2)).isoformat()
    assert account_access(member, now=NOW)["plan"] == "elite"
    assert account_access(member, now=NOW)["status"] == status


def test_paid_downgrade_never_unblocks_suspension_or_changes_lifetime_goat():
    expired = (NOW - timedelta(hours=1)).isoformat()
    suspended = user(app_metadata={
        "blinq_plan": "pro", "blinq_status": "suspended", "blinq_expires_at": expired,
    })
    lifetime = user(app_metadata={
        "blinq_plan": "goat", "blinq_status": "lifetime", "blinq_expires_at": expired,
    })
    assert account_access(suspended, now=NOW)["status"] == "suspended"
    assert account_access(lifetime, now=NOW)["plan"] == "goat"
    assert account_access(lifetime, now=NOW)["status"] == "lifetime"


def test_guarded_worker_write_does_not_overwrite_renewed_firebase_claims(monkeypatch):
    import tbt.services.admin_accounts as admin
    claims = {
        "role": "user", "blinq_plan": "pro", "blinq_status": "active",
        "blinq_expires_at": (NOW + timedelta(days=30)).isoformat(),
    }
    record = SimpleNamespace(custom_claims=claims)
    writes = []
    firebase = SimpleNamespace(
        get_user=lambda *_a, **_kw: record,
        set_custom_user_claims=lambda *_a, **_kw: writes.append(True),
    )
    monkeypatch.setattr(admin, "_firebase_modules", lambda: (None, firebase, None))
    monkeypatch.setattr(admin, "firebase_app", lambda _cfg: object())
    with pytest.raises(admin.AccessConflict):
        admin.update_user_access(
            cfg(), "u1",
            {"role": "user", "plan": "rookie", "status": "active"},
            expected_claims={**claims, "blinq_expires_at": (NOW - timedelta(days=1)).isoformat()},
        )
    assert writes == []
