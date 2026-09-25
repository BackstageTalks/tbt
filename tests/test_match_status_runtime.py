from datetime import datetime, timedelta, timezone

from tbt.services.match_status import classify_finished_event, scan_match_statuses


def _row(event_id="101", winner_id="11", scheduled_at=None):
    scheduled_at = scheduled_at or (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    return {
        "event_id": event_id,
        "scheduled_at": scheduled_at,
        "winner_id": winner_id,
        "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
    }


def _event(event_id="101", winner_code=1, status_type="finished", description="Ended"):
    return {
        "id": event_id,
        "status": {"type": status_type, "description": description},
        "winnerCode": winner_code,
        "homeTeam": {"id": "11", "name": "Alpha"},
        "awayTeam": {"id": "22", "name": "Beta"},
    }


def test_classifies_predicted_winner_and_loser():
    row = _row()
    assert classify_finished_event(row, _event(winner_code=1))["status"] == "win"
    assert classify_finished_event(row, _event(winner_code=2))["status"] == "loss"


def test_retirement_has_priority_over_win_loss():
    row = _row()
    result = classify_finished_event(
        row,
        _event(winner_code=1, status_type="finished", description="Player retired"),
    )
    assert result["status"] == "retired"


class _Provider:
    def __init__(self, *, live=None, previous=None):
        self.live = live or []
        self.previous = previous or {}
        self.previous_calls = []

    def live_events(self):
        return self.live

    def previous_player_matches(self, player_id, page=0):
        self.previous_calls.append((str(player_id), page))
        return {"events": self.previous.get(str(player_id), [])}


def test_scan_skips_currently_live_and_persists_finished_only():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    started = (now - timedelta(hours=1)).isoformat()
    feed = {
        "upcoming": [
            _row("101", "11", started),
            {
                **_row("202", "22", started),
                "player1": {"id": "33", "name": "Gamma"},
                "player2": {"id": "44", "name": "Delta"},
                "winner_id": "44",
            },
        ]
    }
    live = [
        {
            "id": "101",
            "homeTeam": {"id": "11"},
            "awayTeam": {"id": "22"},
            "status": {"type": "inprogress"},
        }
    ]
    previous = {
        "33": [
            {
                "id": "202",
                "status": {"type": "finished", "description": "Ended"},
                "winnerCode": 2,
                "homeTeam": {"id": "33"},
                "awayTeam": {"id": "44"},
            }
        ]
    }
    provider = _Provider(live=live, previous=previous)

    snapshot = scan_match_statuses(feed, provider, now=now, max_checks=10)

    assert "101" not in snapshot["statuses"]
    assert snapshot["statuses"]["202"]["status"] == "win"
    assert snapshot["skipped_live"] == 1
    assert provider.previous_calls == [("33", 0)]


def test_scan_does_not_requery_terminal_snapshot():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    feed = {"upcoming": [_row("101", "11", (now - timedelta(hours=2)).isoformat())]}
    provider = _Provider()
    previous = {
        "statuses": {
            "101": {
                "status": "loss",
                "checked_at": (now - timedelta(hours=1)).isoformat(),
            }
        }
    }

    snapshot = scan_match_statuses(feed, provider, previous, now=now)

    assert snapshot["statuses"]["101"]["status"] == "loss"
    assert provider.previous_calls == []


def test_rejects_wrong_players_even_if_provider_reuses_event_id():
    row = _row()
    wrong = _event(winner_code=1)
    wrong["homeTeam"]["id"] = "999"
    assert classify_finished_event(row, wrong) is None
    wrong["status"] = {"type": "finished", "description": "Player retired"}
    assert classify_finished_event(row, wrong) is None


class _BrokenProvider:
    def __init__(self, error):
        self.error = error
        self.request_count = 0
        self.calls = 0

    def live_events(self):
        self.request_count += 1
        return []

    def previous_player_matches(self, player_id, page=0):
        self.calls += 1
        self.request_count += 1
        raise self.error


def test_broken_player_endpoint_fails_fast_with_safe_diagnostics():
    from tbt.errors import ProviderError
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    feed = {"upcoming": [
        _row(str(100+i), "11", (now - timedelta(minutes=45+10*i)).isoformat())
        for i in range(8)
    ]}
    client = _BrokenProvider(ProviderError("RapidAPI HTTP 403: secrets must not leak"))
    snapshot = scan_match_statuses(feed, client, now=now, max_checks=30)
    assert snapshot["checked"] == 3
    assert client.calls == 3
    assert snapshot["provider_requests"] == 4  # live + 3 failed HTTP calls
    assert snapshot["provider_errors"] == {"ProviderError_HTTP_403": 3}
    assert "secrets" not in repr(snapshot)
    assert snapshot["newly_resolved"] == 0
    assert snapshot["degraded"] is True


def test_quota_error_stops_after_one_history_attempt():
    from tbt.providers.budget import RequestBudgetExceeded
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now - timedelta(hours=1)).isoformat())
    client = _BrokenProvider(RequestBudgetExceeded("No more calls allowed"))
    snapshot = scan_match_statuses({"upcoming": [row]}, client, now=now)
    assert client.calls == 1
    assert snapshot["provider_errors"] == {"RequestBudgetExceeded": 1}
    assert snapshot["degraded"] is True


def test_finished_live_event_can_resolve_without_history_request():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now - timedelta(hours=1)).isoformat())
    client = _Provider(live=[_event()])
    snapshot = scan_match_statuses({"upcoming": [row]}, client, now=now)
    assert snapshot["newly_resolved"] == 1
    assert snapshot["statuses"]["101"]["status"] == "win"
    assert snapshot["checked"] == 0
    assert client.previous_calls == []


def test_valid_but_not_yet_in_previous_matches_is_not_a_provider_failure():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now - timedelta(minutes=60)).isoformat())
    client = _Provider()
    snapshot = scan_match_statuses({"upcoming": [row]}, client, now=now)
    assert snapshot["checked"] == 1
    assert snapshot["successful_history"] == 1
    assert snapshot["degraded"] is False
    assert snapshot["statuses"] == {}


class _NearFallbackProvider:
    def __init__(self, events=None, near_error=None):
        self.events = events or {}
        self.near_error = near_error
        self.request_count = 0
        self.previous_calls = []
        self.near_calls = []

    def live_events(self):
        self.request_count += 1
        return []

    def previous_player_matches(self, player_id, page=0):
        from tbt.errors import ProviderError
        self.request_count += 1
        self.previous_calls.append(str(player_id))
        raise ProviderError("RapidAPI HTTP 404: unknown player or route")

    def near_player_matches_for_status(self, player_id):
        self.request_count += 1
        self.near_calls.append(str(player_id))
        if self.near_error:
            raise self.near_error
        return {"data": {"previousEvent": self.events.get(str(player_id))}}


def test_404_previous_history_uses_valid_near_match_with_identity_check():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    first = _row("101", "11", (now-timedelta(hours=2)).isoformat())
    second = {
        **_row("202", "44", (now-timedelta(hours=1)).isoformat()),
        "player1": {"id": "33"},
        "player2": {"id": "44"},
    }
    event2 = {
        **_event("202", winner_code=2),
        "homeTeam": {"id": "33"},
        "awayTeam": {"id": "44"},
    }
    provider = _NearFallbackProvider({"11": _event(), "33": event2})
    snapshot = scan_match_statuses(
        {"upcoming": [first, second]}, provider, now=now,
        max_checks=10,
    )
    assert snapshot["statuses"]["101"]["status"] == "win"
    assert snapshot["statuses"]["202"]["status"] == "win"
    assert snapshot["newly_resolved"] == 2
    assert snapshot["preferred_route"] == "near"
    assert provider.previous_calls == ["11"]  # only one wasted 404 per batch
    assert provider.near_calls == ["11", "33"]
    assert snapshot["provider_requests"] == 4  # live + 404 + two near


def test_previous_404_snapshot_starts_with_near_route():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    provider = _NearFallbackProvider({"11": _event()})
    previous = {
        "statuses": {},
        "provider_errors": {"ProviderError_HTTP_404": 3},
        "successful_history": 0,
    }
    snapshot = scan_match_statuses(
        {"upcoming": [_row(scheduled_at=(now-timedelta(hours=1)).isoformat())]},
        provider, previous, now=now,
    )
    assert provider.previous_calls == []
    assert snapshot["statuses"]["101"]["status"] == "win"
    assert snapshot["near_attempts"] == 1


def test_near_404_fails_fast_without_fabricating_any_result():
    from tbt.errors import ProviderError
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    feed = {"upcoming": [
        _row(str(101+i), "11", (now-timedelta(minutes=45+10*i)).isoformat())
        for i in range(8)
    ]}
    provider = _NearFallbackProvider(
        near_error=ProviderError("RapidAPI HTTP 404: player not found")
    )
    snapshot = scan_match_statuses(
        feed, provider,
        {"preferred_route": "near"}, now=now, max_checks=30,
    )
    assert provider.previous_calls == []
    assert len(provider.near_calls) == 3
    assert snapshot["degraded"] is True
    assert snapshot["provider_errors"] == {"ProviderError_HTTP_404": 3}
    assert snapshot["newly_resolved"] == 0
    assert snapshot["provider_requests"] == 4


def test_near_mismatched_event_is_not_scored():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    bad = _event()
    bad["homeTeam"]["id"] = "999"
    provider = _NearFallbackProvider({"11": bad})
    snapshot = scan_match_statuses(
        {"upcoming": [_row(scheduled_at=(now-timedelta(hours=1)).isoformat())]},
        provider, {"preferred_route": "near"}, now=now,
    )
    assert snapshot["statuses"] == {}
    assert snapshot["matched_events"] == 1
    assert snapshot["newly_resolved"] == 0
    assert snapshot["degraded"] is False


def test_round_robin_checks_next_pending_id_on_next_run():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    feed = {"upcoming": [
        _row("101", scheduled_at=(now-timedelta(hours=2)).isoformat()),
        _row("202", scheduled_at=(now-timedelta(hours=1)).isoformat()),
    ]}
    provider = _Provider()
    first = scan_match_statuses(feed, provider, now=now, max_checks=1)
    assert first["checked"] == 1
    assert first["next_due_id"] == "202"
    second = scan_match_statuses(feed, provider, first, now=now, max_checks=1)
    assert second["checked"] == 1
    assert second["next_due_id"] == "101"


def test_four_hour_priority_does_not_drop_older_unfinished_today():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    old_today = _row("old", "11", (now-timedelta(hours=5)).isoformat())
    recent = _row("recent", "11", (now-timedelta(hours=1)).isoformat())
    yesterday = _row("yesterday", "11", (now-timedelta(hours=30)).isoformat())
    future = _row("future", "11", (now+timedelta(hours=2)).isoformat())
    provider = _Provider()
    result = scan_match_statuses(
        {"upcoming": [old_today, recent, yesterday, future]},
        provider, now=now, max_checks=1, lookback_hours=4,
    )
    assert result["due"] == 2
    assert result["recent_candidates"] == 1
    assert result["today_candidates"] == 2
    assert result["checked"] == 1
    assert result["pending_count"] == 2
    assert result["next_due_id"] == "old"


def test_thirty_checks_use_current_day_not_unseen_old_backlog():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    rows = []
    for i in range(36):
        row = _row(
            str(1000+i), str(2000+i),
            (now-timedelta(minutes=30+i*5)).isoformat(),
        )
        row["player1"]["id"] = str(2000+i)
        rows.append(row)
    for i in range(40):
        rows.append(_row(
            str(5000+i), str(6000+i),
            (now-timedelta(hours=30, minutes=i)).isoformat(),
        ))
    provider = _Provider()
    result = scan_match_statuses({"upcoming": rows}, provider, now=now, max_checks=30)
    assert result["due"] == 36
    assert result["checked"] == 30
    assert len(provider.previous_calls) == 30
    assert all(str(call[0]).startswith("20") for call in provider.previous_calls)


def test_duplicate_markets_only_cost_one_match_result_lookup():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(minutes=90)).isoformat())
    provider = _Provider()
    result = scan_match_statuses(
        {"upcoming": [row], "daily_picks": [dict(row)],
         "value_picks": [dict(row)]},
        provider, now=now,
    )
    assert result["due"] == 1
    assert result["checked"] == 1
    assert len(provider.previous_calls) == 1


def test_unfinished_previous_day_survives_new_feed_at_six():
    night = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (night-timedelta(hours=5)).isoformat())
    first = scan_match_statuses({"upcoming": [row]}, _Provider(), now=night)
    assert first["checked"] == 1
    assert "101" in first["pending"]
    morning_provider = _Provider(previous={"11": [_event()]})
    morning = scan_match_statuses(
        {"upcoming": []}, morning_provider, first, now=night+timedelta(hours=7),
    )
    assert morning["carryover_candidates"] == 1
    assert morning["checked"] == 1
    assert morning["statuses"]["101"]["status"] == "win"
    assert "101" not in morning["pending"]


def test_live_api_settles_results_beyond_30_history_checks():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    feed = {"upcoming": [
        _row(str(1000+i), "11", (now-timedelta(hours=1)).isoformat())
        for i in range(32)
    ]}
    provider = _Provider(live=[_event("1031")])
    result = scan_match_statuses(feed, provider, now=now, max_checks=30)
    assert result["checked"] == 30
    assert result["statuses"]["1031"]["status"] == "win"
    assert result["newly_resolved"] == 1
    assert result["provider_requests"] == 31


def test_hourly_match_status_schedule_is_local_daytime_only():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/match-status.yml").read_text()
    assert "cron: '17 6-23 * * *'" in workflow
    assert "timezone: Europe/Bratislava" in workflow
    assert "workflow_dispatch:" in workflow
