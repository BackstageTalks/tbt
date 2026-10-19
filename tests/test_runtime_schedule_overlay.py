from datetime import datetime, timedelta, timezone

from tbt.services.match_status import (
    apply_verified_schedule_overlay,
    scan_match_statuses,
    verified_schedule_observation,
)


def row(now):
    return {
        "event_id": "faria-1",
        "scheduled_at": (now - timedelta(minutes=30)).isoformat(),
        "winner_id": "11",
        "player1": {"id": "11"},
        "player2": {"id": "22"},
        "odds": 1.88,
    }


def event(now, status="notstarted"):
    return {
        "id": "faria-1",
        "homeTeam": {"id": "11"},
        "awayTeam": {"id": "22"},
        "status": {"type": status},
        "startTimestamp": int((now + timedelta(hours=4)).timestamp()),
    }


def test_postponement_replaces_only_display_time_and_never_implies_started():
    now = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)
    original = row(now)
    observation = verified_schedule_observation(original, event(now), now)
    assert observation["status"] == "scheduled"
    feed = {"top_daily_picks": [original], "results": [dict(original)]}
    patched = apply_verified_schedule_overlay(feed, {"faria-1": observation}, now=now)
    assert patched["top_daily_picks"][0]["scheduled_at"] == (now + timedelta(hours=4)).isoformat()
    assert patched["top_daily_picks"][0]["runtime_match_started"] is False
    assert patched["top_daily_picks"][0]["odds"] == 1.88
    assert original["scheduled_at"] == (now - timedelta(minutes=30)).isoformat()
    assert patched["results"][0]["scheduled_at"] == original["scheduled_at"]


def test_mismatched_players_or_stale_evidence_fail_closed():
    now = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)
    mismatch = event(now)
    mismatch["awayTeam"] = {"id": "another"}
    assert verified_schedule_observation(row(now), mismatch, now) is None
    valid = verified_schedule_observation(row(now), event(now), now)
    valid["checked_at"] = (now - timedelta(hours=25)).isoformat()
    feed = {"top_daily_picks": [row(now)]}
    apply_verified_schedule_overlay(feed, {"faria-1": valid}, now=now)
    assert "runtime_match_started" not in feed["top_daily_picks"][0]


def test_explicit_live_proof_is_required_for_started_marker():
    now = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)
    live = verified_schedule_observation(row(now), event(now, "inprogress"), now)
    assert live["status"] == "live"
    feed = {"top_daily_picks": [row(now)]}
    apply_verified_schedule_overlay(feed, {"faria-1": live}, now=now)
    assert feed["top_daily_picks"][0]["runtime_match_started"] is True


def test_older_verified_time_remains_visible_without_stale_live_marker():
    now = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)
    observation = verified_schedule_observation(row(now), event(now, "inprogress"), now)
    # Provider LIVE evidence is stale, but the verified revised kickoff
    # is still a useful display-time correction within the betting day.
    observation["checked_at"] = (now - timedelta(hours=3)).isoformat()
    feed = {"top_daily_picks": [row(now)]}
    apply_verified_schedule_overlay(feed, {"faria-1": observation}, now=now)
    displayed = feed["top_daily_picks"][0]
    assert displayed["scheduled_at"] == (now + timedelta(hours=4)).isoformat()
    assert displayed["runtime_match_started"] is False


def test_future_provider_kickoff_overrides_conflicting_live_flag():
    now = datetime(2026, 10, 19, 9, 30, tzinfo=timezone.utc)
    observation = verified_schedule_observation(row(now), event(now, "inprogress"), now)
    assert observation["status"] == "scheduled"
    feed = {"top_daily_picks": [row(now)]}
    apply_verified_schedule_overlay(feed, {"faria-1": observation}, now=now)
    assert feed["top_daily_picks"][0]["runtime_match_started"] is False
