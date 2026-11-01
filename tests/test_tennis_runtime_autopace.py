"""Regression checks for automatic Azure pacing."""
from datetime import datetime, timezone
import pytest
from tbt.providers import shared_budget, shared_rate
from tbt.services import admin_storage

class FakeBudget:
    def __init__(self):
        self.created = []
    def get_entity(self, **kwargs):
        raise KeyError("missing")
    def create_entity(self, entity):
        self.created.append(entity)

def test_runtime_requires_distributed_pace_before_quota(monkeypatch):
    budget = FakeBudget()
    monkeypatch.setenv("FUNCTIONS_WORKER_RUNTIME", "python")
    monkeypatch.setattr(admin_storage, "_table", lambda _: budget)
    calls = []
    def fail_pace(**kwargs):
        calls.append(1)
        raise shared_rate.SharedRateUnavailable("test coordinator unavailable")
    monkeypatch.setattr(shared_rate, "reserve_pace", fail_pace)
    with pytest.raises(shared_rate.SharedRateUnavailable):
        shared_budget.reserve("history", now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    assert calls == [1] and not budget.created

def test_synthetic_table_unchanged_and_explicit_pace(monkeypatch):
    monkeypatch.setenv("FUNCTIONS_WORKER_RUNTIME", "python")
    calls = []
    def pace(**kwargs):
        calls.append(1)
        return {"pace_schema": 1, "max_rps": 6}
    monkeypatch.setattr(shared_rate, "reserve_pace", pace)
    budget = FakeBudget()
    shared_budget.reserve("history", table=budget,
                          now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    assert calls == [] and len(budget.created) == 1
    budget = FakeBudget()
    result = shared_budget.reserve("history", table=budget, paced=True,
                                   now=datetime(2026, 11, 1, 12, tzinfo=timezone.utc))
    assert calls == [1]
    assert result["rate_pace"] == {"schema": 1, "max_rps": 6}
