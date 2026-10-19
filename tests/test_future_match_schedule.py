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
