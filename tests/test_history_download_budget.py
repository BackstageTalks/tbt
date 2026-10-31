"""Regression coverage for auxiliary RapidAPI provider-day safeguards."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from scripts.history_download_budget import (
    LocalRequestBudget, next_provider_reset, reserve_allocation,
)
from tbt.providers.budget import RequestBudgetExceeded


@pytest.mark.parametrize("day,clock", [((2026, 10, 25), 18), ((2027, 7, 1), 19)])
def test_local_reservations_reset_at_1709_utc_across_dst(day, clock):
    old = datetime(*day, 17, 6, tzinfo=timezone.utc)
    new = datetime(*day, 17, 10, tzinfo=timezone.utc)
    assert next_provider_reset(old).astimezone(ZoneInfo("Europe/Bratislava")).hour == clock
    ledger, count = reserve_allocation(None, 14500, now=old)
    assert count == 14500
    _, count = reserve_allocation(ledger, 1, now=old)
    assert count == 0
    with pytest.raises(RequestBudgetExceeded, match="17:07"):
        reserve_allocation(ledger, 1, now=old + timedelta(minutes=2))
    refreshed, count = reserve_allocation(ledger, 14500, now=new)
    assert count == 14500
    assert len(refreshed["reservations"]) == 1
    assert refreshed["reservations"][0]["created_at"] == new.isoformat()


def test_local_ledgers_fail_closed_for_oversized_limits_and_bad_entries(tmp_path):
    with pytest.raises(ValueError, match="14500"):
        reserve_allocation(None, 15000)
    with pytest.raises(ValueError, match="14500"):
        LocalRequestBudget(tmp_path / "too_large.db", limit=15000)
    with pytest.raises(ValueError):
        reserve_allocation({"schema": 1, "reservations": [{"requests": 1}]}, 1)


def test_sqlite_counter_new_day_and_rollover_guard(monkeypatch, tmp_path):
    import scripts.history_download_budget as local

    guard = LocalRequestBudget(tmp_path / "local_quota.db", limit=1)
    old = datetime(2026, 10, 25, 17, 6, tzinfo=timezone.utc)
    new = datetime(2026, 10, 25, 17, 10, tzinfo=timezone.utc)
    try:
        monkeypatch.setattr(local.time, "time", lambda: old.timestamp())
        guard()
        with pytest.raises(RequestBudgetExceeded, match="allowance"):
            guard()
        monkeypatch.setattr(local.time, "time", lambda: (old + timedelta(minutes=2)).timestamp())
        with pytest.raises(RequestBudgetExceeded, match="rollover"):
            guard()
        monkeypatch.setattr(local.time, "time", lambda: new.timestamp())
        guard()
        with pytest.raises(RequestBudgetExceeded, match="allowance"):
            guard()
    finally:
        guard.close()
