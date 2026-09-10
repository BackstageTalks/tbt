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
        "blinq_admin_emails": "",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_new_account_gets_72_hour_rookie_trial_without_stored_plan():
    access = account_access(user(), cfg=cfg(), now=NOW)
    assert access["plan"] == "rookie"
    assert access["plan_label"] == "Rookie Trial"
    assert access["status"] == "trial"
    assert access["expires_at"] == (NOW + timedelta(hours=48)).isoformat()


def test_old_unpaid_account_is_expired():
    access = account_access(
        user(created_at=(NOW - timedelta(days=10)).isoformat()),
        cfg=cfg(),
        now=NOW,
    )
    assert access["plan"] == "expired"
    assert access["status"] == "expired"


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
        ("goat", None, "lifetime"),
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


def test_admin_email_allowlist_bootstraps_admin_without_metadata():
    access = account_access(
        user(email="owner@example.com"),
        cfg=cfg(blinq_admin_emails="owner@example.com, second@example.com"),
        now=NOW,
    )
    assert access["is_admin"] is True
    assert access["role"] == "admin"


def test_lifetime_is_only_valid_for_goat():
    with pytest.raises(ValueError, match="GOAT"):
        normalize_access_update({"role": "user", "plan": "pro", "status": "lifetime"})


def test_active_plan_requires_expiration_date():
    with pytest.raises(ValueError, match="expiration"):
        normalize_access_update({"role": "user", "plan": "pro", "status": "active"})


def test_admin_update_preserves_unrelated_app_metadata_and_records_manual_payment():
    changes = normalize_access_update({
        "role": "user",
        "plan": "elite",
        "status": "active",
        "expires_at": (NOW + timedelta(days=365)).isoformat(),
        "payment_reference": "manual-link-payment-42",
    })
    app = _apply_access_metadata({"provider": "email", "role": "user"}, changes, "admin-1")
    assert app["provider"] == "email"
    assert app["blinq_plan"] == "elite"
    assert app["blinq_status"] == "active"
    assert app["blinq_payment_reference"] == "manual-link-payment-42"
    assert app["blinq_access_updated_by"] == "admin-1"


def test_admin_access_update_can_be_active_without_subscription_plan():
    normalized = normalize_access_update({"role": "admin", "plan": "", "status": "active"})
    assert normalized["role"] == "admin"
    assert normalized["plan"] == ""
    assert normalized["status"] == "active"


def test_avatar_variant_is_user_controlled_presentation_metadata_only():
    account = public_account(
        user(user_metadata={"display_name": "Member", "blinq_avatar_variant": "w"}),
        cfg=cfg(),
        now=NOW,
    )
    invalid = public_account(
        user(user_metadata={"display_name": "Member", "blinq_avatar_variant": "other"}),
        cfg=cfg(),
        now=NOW,
    )
    assert account["avatar_variant"] == "w"
    assert invalid["avatar_variant"] == ""
