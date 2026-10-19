from datetime import datetime, timedelta, timezone
from tbt.services.match_status import scan_match_statuses


def test_future_calendar_sweep_replaces_obsolete_time_before_kickoff():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    fixture = {
        "event_id": "case-1",
        "scheduled_at": (now + timedelta(hours=1)).isoformat(),
        "winner_id": "11",
        "player1": {"id": "11"},
        "player2": {"id": "22"},
    }
    class Provider:
        request_limit = 24
        def __init__(self):
            self.request_count = 0
            self.days = []
        def events_for_status_day(self, day, target_event_ids=None, max_category_requests=8):
            self.request_count += 1
            self.days.append(day.isoformat())
            return {"events": [{
                "id": "case-1",
                "homeTeam": {"id": "11"},
                "awayTeam": {"id": "22"},
                "status": {"type": "notstarted"},
                "startTimestamp": int((now + timedelta(hours=5)).timestamp()),
            }]}
    provider = Provider()
    first = scan_match_statuses(
        {"top_daily_picks": [fixture]}, provider,
        now=now, max_checks=5, max_wall_seconds=22.0,
    )
    assert first["due"] == 0
    assert first["provider_requests"] == 1
    assert provider.days == ["2026-10-19"]
    assert first["schedule_updates"]["case-1"]["scheduled_at"] == (
        now + timedelta(hours=5)
    ).isoformat()
    second = scan_match_statuses(
        {"top_daily_picks": [fixture]}, provider, first,
        now=now + timedelta(hours=2),
    )
    assert second["due"] == 0
    assert second["statuses"] == {}


def test_upcoming_observation_is_id_matched_and_does_not_touch_settlement():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    fixture = {
        "event_id": "faria-3", "scheduled_at": (now + timedelta(hours=2)).isoformat(),
        "winner_id": "11", "player1": {"id": "11"}, "player2": {"id": "22"},
        "odds": 1.85,
    }
    class Provider:
        request_count = 0
        def events_for_status_day(self, day, target_event_ids=None, max_category_requests=8):
            assert max_category_requests <= 5
            assert target_event_ids == {"faria-3"}
            self.request_count += 1
            return {"events": [
                {"id": "faria-3", "homeTeam": {"id": "11"}, "awayTeam": {"id": "999"},
                 "status": {"type": "notstarted"},
                 "startTimestamp": int((now + timedelta(hours=6)).timestamp())}
            ]}
    result = scan_match_statuses({"top_daily_picks": [fixture]}, Provider(), now=now)
    assert result["prestart_checked"] == 1
    assert result["prestart_verified"] == 0
    assert result["schedule_updates"] == {}
    assert result["statuses"] == {}
    assert fixture["odds"] == 1.85


def test_prestart_worker_rechecks_verified_shift_without_marking_started():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    fixture = {
        "event_id": "faria-4", "scheduled_at": (now + timedelta(hours=1)).isoformat(),
        "winner_id": "11", "player1": {"id": "11"}, "player2": {"id": "22"},
    }
    class Provider:
        request_count = 0
        def events_for_status_day(self, day, target_event_ids=None, max_category_requests=8):
            self.request_count += 1
            return {"events": [{
                "id": "faria-4", "homeTeam": {"id": "11"}, "awayTeam": {"id": "22"},
                "status": {"type": "notstarted"},
                "startTimestamp": int((now + timedelta(hours=4)).timestamp())
            }]}
    client = Provider()
    initial = scan_match_statuses({"top_daily_picks": [fixture]}, client, now=now)
    assert initial["prestart_verified"] == 1
    assert initial["due"] == 0
    assert initial["schedule_updates"]["faria-4"]["status"] == "scheduled"
    updated = scan_match_statuses({"top_daily_picks": [fixture]}, client, initial,
                                   now=now + timedelta(hours=2))
    assert updated["due"] == 0
    assert updated["statuses"] == {}
    assert updated["prestart_verified"] == 1


def test_prestart_sweep_never_polls_unpublished_board_candidates():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    public_row = {
        "event_id": "published-1", "scheduled_at": (now + timedelta(hours=2)).isoformat(),
        "winner_id": "11", "player1": {"id": "11"}, "player2": {"id": "22"},
    }
    unpublished = {
        **public_row, "event_id": "unpublished-internal",
    }
    class Provider:
        request_count = 0
        def events_for_status_day(self, day, target_event_ids=None, max_category_requests=8):
            self.request_count += 1
            assert target_event_ids == {"published-1"}
            return {"events": [{
                "id": "published-1", "homeTeam": {"id": "11"}, "awayTeam": {"id": "22"},
                "status": {"type": "notstarted"},
                "startTimestamp": int((now + timedelta(hours=4)).timestamp()),
            }]}
    feed = {
        "top_daily_picks": [public_row],
        "upcoming": [unpublished],
        "board_upcoming": [unpublished],
    }
    result = scan_match_statuses(feed, Provider(), now=now, max_wall_seconds=22.0)
    assert result["prestart_checked"] == 1
    assert result["prestart_verified"] == 1
    assert set(result["schedule_updates"]) == {"published-1"}
