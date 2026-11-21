"""No-provider-spend contract for the 16:50 BlinQ shared-budget admin email."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tbt.services.api_budget_underuse_alert import (
    ALERT_BELOW, BudgetAlertUnavailable, check_due, send_underuse_alert,
)

CET = datetime(2026, 11, 22, 15, 50, tzinfo=timezone.utc)
CEST = datetime(2026, 7, 15, 14, 50, tzinfo=timezone.utc)


def snapshot(spent=11249, *, summer=False):
    reset = "2026-07-15T17:09:00+00:00" if summer else "2026-11-22T17:09:00+00:00"
    return {
        "schema": 2, "window": "provider_day_17_09_utc",
        "provider_plan_limit": 15000,
        "global_limit": 14500,
        "reserved_provider_headroom": 500,
        "global_spent": spent, "global_remaining": 14500 - spent,
        "next_reset_utc": reset,
    }


class AlreadyExists(Exception):
    status_code = 409


class FakeTable:
    def __init__(self):
        self.rows = {}
        self.create_calls = 0

    def create_entity(self, entity):
        self.create_calls += 1
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise AlreadyExists("Claim already exists")
        self.rows[key] = dict(entity)

    def upsert_entity(self, entity, mode=None):
        key = (entity["PartitionKey"], entity["RowKey"])
        self.rows[key].update(dict(entity))

    def get_entity(self, partition_key, row_key):
        return dict(self.rows[(partition_key, row_key)])


def cfg(*, recipients="ops@example.test"):
    return SimpleNamespace(
        blinq_admin_emails=recipients, blinq_admin_email="",
        blinq_smtp_host="smtp.example.test", blinq_smtp_from="BlinQ <ops@example.test>",
        blinq_smtp_port=587, blinq_public_url="https://blinq.example",
    )


@pytest.mark.parametrize(("at", "summer"), [(CET, False), (CEST, True)])
def test_only_real_provider_day_and_dst_aware_1650_is_eligible(at, summer):
    result = check_due(at, snapshot(11249, summer=summer))
    assert result["status"] == "notify"
    assert result["threshold_requests"] == 11250
    assert result["global_spent"] == 11249
    assert result["percent"] < 75
    assert result["reset_local"].startswith("2026-07-15T19:09" if summer else "2026-11-22T18:09")


@pytest.mark.parametrize("minutes", [-2, -1, 16, 20, 60])
def test_no_mail_outside_1650_1705_catchup_window(minutes):
    assert check_due(CET + timedelta(minutes=minutes), snapshot())["status"] == "not_due"


@pytest.mark.parametrize(("spent", "expected"), [
    (0, "notify"),
    (11249, "notify"),
    (11250, "threshold_met"),
    (14500, "threshold_met"),
])
def test_strictly_less_than_75_percent_of_provider_15000(spent, expected):
    assert ALERT_BELOW == 11250
    assert check_due(CET, snapshot(spent))["status"] == expected


@pytest.mark.parametrize("corruption", [
    {"schema": 1},
    {"provider_plan_limit": 14500},
    {"global_limit": 15000},
    {"reserved_provider_headroom": 0},
    {"window": "UTC midnight"},
    {"global_spent": True},
    {"global_remaining": 9999},
    {"next_reset_utc": "2026-11-23T17:09:00+00:00"},
    {"next_reset_utc": "garbage"},
])
def test_unknown_or_corrupt_budget_never_sends(corruption):
    with pytest.raises(BudgetAlertUnavailable):
        check_due(CET, {**snapshot(), **corruption})


def test_sends_one_admin_email_and_durable_readback_without_provider_request():
    t = FakeTable()
    messages = []

    def send(_cfg, recipient, **kwargs):
        messages.append((recipient, kwargs))
        return True

    reader_calls = []

    def read_only():
        reader_calls.append(True)
        return snapshot(884)

    result = send_underuse_alert(cfg(), now=CET, budget_reader=read_only,
                                table=t, sender=send)
    assert result["status"] == "smtp_accepted"
    assert result["accepted_count"] == 1
    assert len(reader_calls) == 1
    assert t.create_calls == 1
    assert len(messages) == 1
    assert "884" in messages[0][1]["body_en"]
    assert "75 %" in messages[0][1]["subject"] or "75 %" in messages[0][1]["body_sk"]
    stored = list(t.rows.values())[0]
    assert stored["state"] == "smtp_accepted"
    assert stored["accepted_count"] == 1
    assert "ops@example.test" not in str(stored)

    # Second external cron retry must not attempt another SMTP delivery.
    duplicate = send_underuse_alert(cfg(), now=CET + timedelta(minutes=10),
                                    budget_reader=read_only, table=t, sender=send)
    assert duplicate["status"] == "already_claimed"
    assert len(messages) == 1


def test_threshold_not_met_no_storage_claim_no_email():
    t = FakeTable()
    result = send_underuse_alert(cfg(), now=CET, budget_reader=lambda: snapshot(11250),
                                table=t, sender=lambda *args, **kwargs: pytest.fail("no SMTP"))
    assert result["status"] == "threshold_met"
    assert t.create_calls == 0


def test_unknown_mail_outcome_claims_once_and_blocks_automatic_retry():
    t = FakeTable()
    calls = []

    def failed_sender(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("Unknown SMTP outcome")

    with pytest.raises(BudgetAlertUnavailable, match="no auto retry"):
        send_underuse_alert(cfg(), now=CET, budget_reader=snapshot, table=t,
                            sender=failed_sender)
    assert list(t.rows.values())[0]["state"] == "outcome_uncertain"
    repeat = send_underuse_alert(cfg(), now=CET + timedelta(minutes=3),
                                 budget_reader=snapshot, table=t, sender=failed_sender)
    assert repeat["status"] == "already_claimed"
    assert len(calls) == 1


def test_missing_admin_mail_or_smtp_does_not_claim_or_send():
    t = FakeTable()
    with pytest.raises(BudgetAlertUnavailable, match="recipients"):
        send_underuse_alert(cfg(recipients=""), now=CET,
                            budget_reader=snapshot, table=t,
                            sender=lambda *_a, **_k: pytest.fail("no SMTP"))
    assert t.create_calls == 0


def test_external_clock_workflows_do_not_add_native_cron():
    root = Path(__file__).resolve().parents[1]
    alert = (root / ".github/workflows/api-budget-underuse-notify.yml").read_text()
    clock = (root / ".github/workflows/match-status.yml").read_text()
    assert "schedule:" not in alert
    assert "workflow_dispatch:" in alert
    assert "Europe/Bratislava" in alert
    assert "api-budget-underuse-notify.yml" in clock
    assert "X-Blinq-Worker-Token:" in alert
    assert "--retry 0" in alert
