import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from download_tennis_history import download_days, merge_match
from history_download_budget import LocalRequestBudget, reserve_allocation
from tbt.providers.budget import RequestBudgetExceeded


def test_cancelled_runs_keep_reserved_allowance():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    ledger, granted = reserve_allocation({}, 9000, now)
    assert granted == 9000
    ledger, granted = reserve_allocation(ledger, 5000, now)
    assert granted == 3000
    assert reserve_allocation(ledger, 5000, now + timedelta(hours=26))[1] == 0
    assert reserve_allocation(ledger, 5000, now + timedelta(hours=28))[1] == 5000


def test_local_budget_is_shared_across_instances_and_restarts(tmp_path):
    path = tmp_path / "budget.sqlite"
    first = LocalRequestBudget(path, limit=2)
    second = LocalRequestBudget(path, limit=2)
    first()
    second()
    first.close()
    with pytest.raises(RequestBudgetExceeded):
        second()
    second.close()
    resumed = LocalRequestBudget(path, limit=2)
    with pytest.raises(RequestBudgetExceeded):
        resumed()
    resumed.close()


def test_incomplete_day_is_retried_without_duplicate_rows(match_factory):
    class Provider:
        request_count = 0
        stop = True
        def matches_for_day(self, tour, day, historical):
            self.request_count += 1
            if tour == "wta" and self.stop:
                raise RequestBudgetExceeded()
            return [match_factory(tour, "A", "B", "A", tour=tour)]
    provider = Provider()
    matches, progress = {}, {"completed_days": []}
    day = date(2025, 1, 1)
    with pytest.raises(RequestBudgetExceeded):
        download_days(provider, matches, progress, day, day, lambda *a: None)
    assert progress["completed_days"] == []
    provider.stop = False
    download_days(provider, matches, progress, day, day, lambda *a: None)
    assert len(matches) == 2
    assert progress["completed_days"] == ["2025-01-01"]
    calls = provider.request_count
    download_days(provider, matches, progress, day, day, lambda *a: None)
    assert provider.request_count == calls


def test_merge_preserves_statistics_when_provider_changes_orientation(match_factory):
    old = match_factory("m", "A", "B", "A")
    old.stats = {"p1_service_points_won": .7, "p2_service_points_won": .6}
    incoming = old.swapped()
    incoming.stats = {}
    merged = merge_match(old, incoming)
    assert merged.stats == {"p1_service_points_won": .6, "p2_service_points_won": .7}


def test_invalid_ledger_fails_closed():
    with pytest.raises(ValueError):
        reserve_allocation({"schema": 99}, 1000)
