from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tbt.schemas import MatchRecord


@pytest.fixture
def match_factory():
    def make(
        match_id: str,
        p1: str,
        p2: str,
        winner: str | None,
        day: int = 1,
        surface: str = "hard",
        tour: str = "atp",
    ) -> MatchRecord:
        return MatchRecord(
            match_id=match_id,
            tour=tour,
            scheduled_at=datetime(2025, 1, day, 12, tzinfo=timezone.utc),
            player1_id=p1,
            player1_name=p1,
            player2_id=p2,
            player2_name=p2,
            winner_id=winner,
            surface=surface,
            tournament="Test Open",
            tournament_level="ATP 250",
        )

    return make


# Provider-unit tests use mocked HTTP/storage and must not depend on the UTC
# wall clock of the GitHub runner. Otherwise a harmless CI run during the
# protected 17:07–17:10 UTC RapidAPI reset fails unrelated contract assertions.
# This fixture NEVER changes production code or bypasses rollover verification:
# the dedicated safety tests pass an explicit 17:08 UTC and assert denial.
_PROVIDER_CLOCK_TEST_MODULES = frozenset({
    "test_history_download_budget.py",
    "test_history_downloader.py",
    "test_match_status_runtime.py",
    "test_remaining_regressions.py",
    "test_shared_api_budget.py",
    "test_tennis_optional_http_guards.py",
})


@pytest.fixture(autouse=True)
def deterministic_provider_contract_clock(request, monkeypatch):
    if request.node.path.name not in _PROVIDER_CLOCK_TEST_MODULES:
        return

    class FrozenProviderClock(datetime):
        @classmethod
        def now(cls, tz=None):
            observed = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
            return observed.astimezone(tz) if tz is not None else observed.replace(tzinfo=None)

    from tbt.providers import rapidapi, shared_budget
    import scripts.history_download_budget as local_history_budget

    # All patching is scoped to one test invocation and automatically restored.
    # fromtimestamp() is deliberately NOT overridden: tests that monkeypatch
    # local_history_budget.time.time still exercise the real rollover guard.
    monkeypatch.setattr(rapidapi, "datetime", FrozenProviderClock)
    monkeypatch.setattr(shared_budget, "datetime", FrozenProviderClock)
    monkeypatch.setattr(local_history_budget, "datetime", FrozenProviderClock)
