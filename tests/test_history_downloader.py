from dataclasses import replace
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


def test_cross_year_provider_correction_checkpoints_both_partitions(match_factory):
    old_time = datetime(2024, 12, 31, 23, tzinfo=timezone.utc)
    new_time = datetime(2025, 1, 1, 1, tzinfo=timezone.utc)
    old = replace(
        match_factory("old", "A", "B", "A"),
        scheduled_at=old_time,
        provider_payload={"_tbt_provider_event_id": "event-123"},
    )
    incoming = replace(
        old,
        match_id="new",
        scheduled_at=new_time,
        provider_payload={"_tbt_provider_event_id": "event-123"},
    )

    class Provider:
        request_count = 0
        def matches_for_day(self, tour, day, historical):
            self.request_count += 1
            return [incoming] if tour == "atp" else []

    matches = {old.match_id: old}
    progress = {"completed_days": []}
    checkpoints = []
    download_days(
        Provider(),
        matches,
        progress,
        new_time.date(),
        new_time.date(),
        lambda years, publish=False: checkpoints.append((set(years), publish)),
    )

    assert checkpoints[0][0] == {2024, 2025}
    assert len(matches) == 1
    only = next(iter(matches.values()))
    assert only.scheduled_at == new_time
    assert progress["completed_days"] == ["2025-01-01"]


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


def test_reopen_history_gap_days_for_missing_partition(match_factory):
    from download_tennis_history import reopen_history_gap_days
    progress = {"completed_days": ["2026-01-01", "2026-01-02", "2025-12-31"]}
    result = reopen_history_gap_days({}, progress, date(2026, 1, 1), date(2026, 1, 2), {2025})
    assert result["missing_partition_years"] == [2026]
    assert result["partial_partition_years"] == []
    assert sorted(result["reopened_days"]) == ["2026-01-01", "2026-01-02"]
    assert progress["completed_days"] == ["2025-12-31"]


def test_reopen_history_gap_days_for_catastrophically_partial_partition(match_factory):
    from download_tennis_history import reopen_history_gap_days
    completed = [f"2026-01-{day:02d}" for day in range(1, 21)]
    progress = {"completed_days": completed.copy()}
    match = replace(
        match_factory("m1", "A", "B", "A"),
        scheduled_at=datetime(2026, 1, 20, 12, tzinfo=timezone.utc),
    )
    result = reopen_history_gap_days(
        {match.match_id: match}, progress, date(2026, 1, 1), date(2026, 1, 20), {2026}
    )
    assert result["missing_partition_years"] == []
    assert result["partial_partition_years"] == [2026]
    assert len(result["reopened_days"]) == 19
    assert progress["completed_days"] == ["2026-01-20"]


def test_reopen_history_gap_days_does_not_touch_healthy_partition(match_factory):
    from download_tennis_history import reopen_history_gap_days
    completed = [f"2026-01-{day:02d}" for day in range(1, 21)]
    matches = {}
    for day in range(1, 16):
        match = replace(
            match_factory(f"m{day}", f"A{day}", f"B{day}", f"A{day}"),
            scheduled_at=datetime(2026, 1, day, 12, tzinfo=timezone.utc),
        )
        matches[match.match_id] = match
    progress = {"completed_days": completed.copy()}
    result = reopen_history_gap_days(matches, progress, date(2026, 1, 1), date(2026, 1, 20), {2026})
    assert result["partial_partition_years"] == []
    assert result["reopened_days"] == []
    assert progress["completed_days"] == completed
