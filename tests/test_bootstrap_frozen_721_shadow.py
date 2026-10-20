"""Safety and provenance tests for zero-provider prospective bootstrap."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import bootstrap_frozen_721_shadow as bootstrap


def prediction(*, when, issued, created=None, model=bootstrap.CHAMPION_VERSION,
               match_id="fixture-1", surface="hard", tour="ATP"):
    return {
        "id": match_id, "model_version": model,
        "tour": tour, "surface": surface, "round": "quarterfinal",
        "tournament": "Protected research only", "tournament_id": "t-1",
        "competition": "atp_250", "best_of": 3,
        "scheduled_at": when.isoformat(),
        "issued_at": issued.isoformat(),
        "created_at": (created or issued - timedelta(minutes=2)).isoformat(),
        "player1": {"id": "123", "name": "A", "rank": 40, "probability": 0.61},
        "player2": {"id": "456", "name": "B", "rank": 90, "probability": 0.39},
    }


def test_only_already_issued_future_matches_and_exact_champion():
    now = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
    good = prediction(when=now + timedelta(hours=9), issued=now - timedelta(hours=1))
    past = prediction(when=now - timedelta(minutes=1), issued=now-timedelta(hours=2),match_id="past")
    not_issued = prediction(when=now+timedelta(hours=3),issued=now+timedelta(minutes=1),match_id="unissued")
    alien = prediction(when=now+timedelta(hours=3),issued=now-timedelta(hours=1), model="older",match_id="alien")
    future = prediction(when=now+timedelta(days=6),issued=now-timedelta(hours=1),match_id="too-far")
    duplicate = dict(good)
    feed = {"model": {"version": bootstrap.CHAMPION_VERSION},
            "upcoming": [good,past,not_issued,alien,future,duplicate]}
    rows, fixtures = bootstrap.eligible_issued_fixtures(feed, now)
    assert len(rows) == len(fixtures) == 1
    assert rows[0]["id"] == "fixture-1"
    fixture=fixtures[0]
    assert fixture.match_id == "fixture-1"
    assert fixture.player1_rank == 40
    assert fixture.player2_rank == 90
    assert fixture.scheduled_at > now
    assert fixture.status == "upcoming"
    assert fixture.tour == "atp"


def test_bad_feed_version_fails_closed():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="Wrong production feed"):
        bootstrap.eligible_issued_fixtures(
            {"model": {"version": "unverified"}, "upcoming": []}, now
        )


def test_never_counts_naive_timestamps_or_unissued_rows():
    now = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
    row = prediction(when=now + timedelta(hours=3),
                     issued=now - timedelta(minutes=1))
    row["issued_at"] = "2026-10-20T17:59:00"
    feed = {"model": {"version": bootstrap.CHAMPION_VERSION}, "upcoming": [row]}
    predictions, fixtures = bootstrap.eligible_issued_fixtures(feed, now)
    assert predictions == fixtures == []


def test_existing_shadow_probe_returns_without_loading_history(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setattr(
        bootstrap, "ReleaseStore",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Existing release must not be modified")
        ),
    )
    import release_store
    monkeypatch.setattr(release_store, "_run_gh",
                        lambda args: SimpleNamespace(returncode=0,stderr=""))
    result=bootstrap.bootstrap(cache=tmp_path)
    assert result["status"] == "SKIPPED_EXISTING_PRIVATE_SHADOW"
    assert result["provider_requests"] == 0
