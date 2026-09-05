from datetime import datetime, timedelta, timezone

from tbt.repositories.supabase import SupabaseRepository


def _repo_without_init() -> SupabaseRepository:
    return object.__new__(SupabaseRepository)


def _identity_repo() -> tuple[SupabaseRepository, dict]:
    repo = _repo_without_init()
    captured: dict = {}

    def fake_select_all(table, filters=None, order=None, **kwargs):
        captured["table"] = table
        captured["filters"] = dict(filters or {})
        captured["order"] = order

        return [
            {
                "match_id": "a",
                "scheduled_at": "2026-09-01T00:00:00+00:00",
            },
            {
                "match_id": "b",
                "scheduled_at": "2026-09-02T00:00:00+00:00",
            },
        ]

    repo.select_all = fake_select_all

    # Keep the real _match_from_row implementation.
    # get_completed_matches() returns MatchRecord objects.
    repo._hydrate_environments = lambda matches: list(matches)
    repo._dedupe_completed_matches = lambda matches: list(matches)

    return repo, captured


def test_completed_match_read_is_rolling_hot_tier_not_full_history():
    """
    Regression guard for V20.7+:
    completed reads must be time-bounded in Supabase.
    """
    repo, captured = _identity_repo()

    before = datetime.now(timezone.utc) + timedelta(hours=1)

    matches = repo.get_completed_matches(before=before)

    assert [match.match_id for match in matches] == ["a", "b"]

    assert captured["table"] == "matches"
    assert captured["order"] == "scheduled_at.asc"

    filters = captured["filters"]

    assert filters["winner_id"] == "not.is.null"
    assert filters["scheduled_at"].startswith("gte.")
    assert "scheduled_at.lt." in filters["and"]

    cutoff = datetime.fromisoformat(
        filters["scheduled_at"].removeprefix("gte.")
    )

    # Default policy is rolling and evaluated at runtime.
    # Allow a broad range so this test does not hard-code
    # a calendar year or a particular retention setting.
    age = datetime.now(timezone.utc) - cutoff

    assert timedelta(days=13) <= age <= timedelta(days=181)


def test_completed_matches_since_uses_explicit_delta_window():
    """
    Checkpoint replay must read only the explicit Supabase delta window.
    """
    repo, captured = _identity_repo()

    after = datetime(
        2026,
        8,
        1,
        12,
        0,
        tzinfo=timezone.utc,
    )

    before = datetime(
        2026,
        9,
        1,
        12,
        0,
        tzinfo=timezone.utc,
    )

    matches = repo.get_completed_matches_since(
        after=after,
        before=before,
    )

    assert [match.match_id for match in matches] == ["a", "b"]

    filters = captured["filters"]

    assert filters["winner_id"] == "not.is.null"
    assert filters["scheduled_at"] == f"gte.{after.isoformat()}"
    assert filters["and"] == (
        f"(scheduled_at.lt.{before.isoformat()})"
    )
