from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tbt.services.auth import account_access, public_account
from tbt.services.admin_accounts import normalize_access_update, update_user_access


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
        "supabase_url": "https://supabase.test",
        "supabase_service_role_key": "service",
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


def test_hide_ads_is_only_honoured_for_active_elite_or_goat():
    elite = public_account(
        user(
            user_metadata={"display_name": "Member", "blinq_hide_ads": True},
            app_metadata={
                "blinq_plan": "elite",
                "blinq_status": "active",
                "blinq_expires_at": (NOW + timedelta(days=365)).isoformat(),
            },
        ),
        cfg=cfg(),
        now=NOW,
    )
    pro = public_account(
        user(
            user_metadata={"display_name": "Member", "blinq_hide_ads": True},
            app_metadata={
                "blinq_plan": "pro",
                "blinq_status": "active",
                "blinq_expires_at": (NOW + timedelta(days=30)).isoformat(),
            },
        ),
        cfg=cfg(),
        now=NOW,
    )
    assert elite["hide_ads_allowed"] is True
    assert elite["hide_ads"] is True
    assert pro["hide_ads_allowed"] is False
    assert pro["hide_ads"] is False


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


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self):
        self.put_payload = None

    def get(self, url, **kwargs):
        return FakeResponse(200, user(app_metadata={"provider": "email", "role": "user"}))

    def put(self, url, **kwargs):
        self.put_payload = kwargs["json"]
        updated = user(app_metadata=kwargs["json"]["app_metadata"])
        return FakeResponse(200, updated)


def test_admin_update_preserves_unrelated_app_metadata_and_records_manual_payment():
    client = FakeClient()
    updated = update_user_access(
        cfg(),
        "u1",
        {
            "role": "user",
            "plan": "elite",
            "status": "active",
            "expires_at": (NOW + timedelta(days=365)).isoformat(),
            "payment_reference": "manual-link-payment-42",
        },
        actor_id="admin-1",
        client=client,
    )
    app = updated["app_metadata"]
    assert app["provider"] == "email"
    assert app["blinq_plan"] == "elite"
    assert app["blinq_status"] == "active"
    assert app["blinq_payment_reference"] == "manual-link-payment-42"
    assert app["blinq_access_updated_by"] == "admin-1"
