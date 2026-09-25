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
        _row(str(100+i), "11", (now - timedelta(hours=2+i)).isoformat())
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
    row = _row("101", "11", (now - timedelta(minutes=10)).isoformat())
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
        _row(str(101+i), "11", (now-timedelta(hours=i+1)).isoformat())
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



def test_scheduled_time_defers_near_lookup_until_ninety_minutes():
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    provider = _NearFallbackProvider({"11": _event()})
    pending = _row("101", "11", (now - timedelta(minutes=40)).isoformat())
    early = scan_match_statuses(
        {"upcoming": [pending]}, provider, {"preferred_route": "near"},
        now=now, min_start_age_minutes=90,
    )
    assert early["due"] == 1
    assert early["checkable_now"] == 0
    assert early["deferred_recent"] == 1
    assert early["checked"] == 0
    assert provider.near_calls == []
    assert early["newly_resolved"] == 0

    later = scan_match_statuses(
        {"upcoming": [pending]}, provider, early,
        now=now + timedelta(minutes=60), min_start_age_minutes=90,
    )
    assert later["checkable_now"] == 1
    assert provider.near_calls == ["11"]
    assert later["statuses"]["101"]["status"] == "win"


def test_completed_live_match_can_resolve_before_scheduled_wait():
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    provider = _Provider(live=[_event()])
    feed = {"upcoming": [_row(scheduled_at=(now-timedelta(minutes=15)).isoformat())]}
    snapshot = scan_match_statuses(feed, provider, now=now, min_start_age_minutes=90)
    assert snapshot["newly_resolved"] == 1
    assert snapshot["statuses"]["101"]["status"] == "win"
    assert provider.previous_calls == []


def test_today_top_unique_match_is_checked_before_yesterdays_backlog():
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    old = _row("101", "11", (now-timedelta(hours=19)).isoformat())
    top = {
        **_row("202", "33", (now-timedelta(hours=3)).isoformat()),
        "player1": {"id": "33", "name": "Gamma"},
        "player2": {"id": "44", "name": "Delta"},
    }
    top_result = {
        **_event("202", winner_code=1),
        "homeTeam": {"id": "33"},
        "awayTeam": {"id": "44"},
    }
    provider = _NearFallbackProvider({"11": _event(), "33": top_result})
    feed = {"upcoming": [old, top], "daily_picks": [top, dict(top)]}
    snap = scan_match_statuses(
        feed, provider, {"preferred_route": "near"},
        now=now, max_near_checks=1, min_start_age_minutes=90,
    )
    assert snap["tracked"] == 2  # duplicate TOP bet never causes duplicate lookup
    assert snap["focus_due"] == 1
    assert provider.near_calls == ["33"]
    assert snap["statuses"]["202"]["status"] == "win"
    assert "101" not in snap["statuses"]


def test_unfinished_near_event_waits_for_retry_window():
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    pending = _row(scheduled_at=(now-timedelta(hours=3)).isoformat())
    provider = _NearFallbackProvider()
    feed = {"upcoming": [pending]}
    first = scan_match_statuses(
        feed, provider, {"preferred_route": "near"}, now=now,
        min_start_age_minutes=90, retry_after_minutes=120,
    )
    assert first["checked"] == 1
    assert first["unmatched"] == 1
    assert first["last_checked_at"]["101"] == now.isoformat()
    second = scan_match_statuses(
        feed, provider, first, now=now+timedelta(hours=1),
        min_start_age_minutes=90, retry_after_minutes=120,
    )
    assert second["checked"] == 0
    assert second["deferred_cooldown"] == 1
    assert provider.near_calls == ["11"]
    third = scan_match_statuses(
        feed, provider, second, now=now+timedelta(hours=2, minutes=1),
        min_start_age_minutes=90, retry_after_minutes=120,
    )
    assert third["checked"] == 1
    assert provider.near_calls == ["11", "11"]


def test_cursor_rotates_within_todays_priority_not_into_old_backlog():
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    first = _row("101", scheduled_at=(now-timedelta(hours=3)).isoformat())
    second = _row("202", scheduled_at=(now-timedelta(hours=2)).isoformat())
    older = _row("303", scheduled_at=(now-timedelta(hours=20)).isoformat())
    feed = {"upcoming": [older, first, second], "daily_picks": [first, second]}
    provider = _NearFallbackProvider()
    a = scan_match_statuses(
        feed, provider, {"preferred_route": "near"}, now=now,
        max_checks=1, max_near_checks=1, min_start_age_minutes=90,
    )
    assert a["next_due_id"] == "202"
    b = scan_match_statuses(
        feed, provider, a, now=now, max_checks=1, max_near_checks=1,
        min_start_age_minutes=90,
    )
    assert b["next_due_id"] == "101"
