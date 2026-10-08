from pathlib import Path
from datetime import datetime, timedelta, timezone

from tbt.services.match_status import classify_finished_event, runtime_settled_results, scan_match_statuses


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


def test_classification_preserves_first_set_comeback_context():
    row = _row()
    event = _event(winner_code=1)
    event["homeScore"] = {"period1": 4, "period2": 6, "period3": 6}
    event["awayScore"] = {"period1": 6, "period2": 3, "period3": 2}
    result = classify_finished_event(row, event)
    assert result["status"] == "win"
    assert result["first_set_outcome"] == "loss"
    assert result["first_set_score"] == "4:6"


def test_walkover_w_o_is_terminal_void_even_if_provider_lists_winner():
    row = _row()
    result = classify_finished_event(
        row, _event(winner_code=1, status_type="finished", description="W/O"),
    )
    assert result["status"] == "void"


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


class _DailyStatusProvider(_NearFallbackProvider):
    def __init__(self, daily_events):
        super().__init__({})
        self.daily_events = daily_events
        self.daily_calls = []

    def events_for_status_day(self, day, target_event_ids=None, max_category_requests=8):
        self.request_count += 1
        self.daily_calls.append(day.isoformat())
        assert target_event_ids
        assert max_category_requests <= 8
        return {"events": list(self.daily_events)}


def test_daily_exact_event_lookup_resolves_same_day_rows_in_one_request():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    first = _row("101", "11", (now-timedelta(hours=2)).isoformat())
    second = _row("102", "22", (now-timedelta(hours=1)).isoformat())
    event1 = _event("101", winner_code=1)
    event2 = _event("102", winner_code=2)
    provider = _DailyStatusProvider([event1, event2])

    snapshot = scan_match_statuses(
        {"upcoming": [first, second]}, provider,
        {"preferred_route": "near"}, now=now, max_checks=10, max_near_checks=10,
    )

    assert provider.daily_calls == ["2026-09-24"]
    assert provider.near_calls == []
    assert snapshot["statuses"]["101"]["status"] == "win"
    assert snapshot["statuses"]["102"]["status"] == "win"
    assert snapshot["newly_resolved"] == 2
    assert snapshot["daily_attempts"] == 1
    assert snapshot["daily_matches"] == 2
    assert snapshot["provider_requests"] == 2  # live + one daily listing


def test_daily_lookup_error_is_reported_without_disabling_near_fallback():
    from tbt.errors import ProviderError

    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(hours=2)).isoformat())

    class Daily403Provider(_NearFallbackProvider):
        def events_with_odds_for_status_day(self, day):
            self.request_count += 1
            raise ProviderError("RapidAPI HTTP 403: plan restricted")

    provider = Daily403Provider({"11": _event("101", winner_code=1)})
    snapshot = scan_match_statuses(
        {"upcoming": [row]}, provider,
        {"preferred_route": "near"}, now=now, max_checks=10, max_near_checks=10,
    )

    assert snapshot["daily_attempts"] == 1
    assert snapshot["daily_matches"] == 0
    assert snapshot["daily_errors"] == {"ProviderError_HTTP_403": 1}
    assert provider.near_calls == ["11"]
    assert snapshot["statuses"]["101"]["status"] == "win"
    assert snapshot["degraded"] is False


def test_near_fallback_checks_second_player_when_first_players_near_event_misses_target():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(hours=2)).isoformat())
    row["player1"] = {"id": "11"}
    row["player2"] = {"id": "22"}

    unrelated = _event("999")
    unrelated["homeTeam"] = {"id": "11"}
    unrelated["awayTeam"] = {"id": "33"}
    target = _event("101", winner_code=2)
    target["homeTeam"] = {"id": "11"}
    target["awayTeam"] = {"id": "22"}

    provider = _NearFallbackProvider({"11": unrelated, "22": target})
    snapshot = scan_match_statuses(
        {"upcoming": [row]}, provider,
        {"preferred_route": "near"}, now=now, max_checks=10, max_near_checks=10,
    )

    assert provider.near_calls == ["11", "22"]
    assert snapshot["statuses"]["101"]["status"] == "loss"
    assert snapshot["newly_resolved"] == 1
    assert snapshot["matched_events"] == 1
    assert snapshot["unmatched"] == 0


def test_near_cap_rotates_to_second_player_on_next_run_without_extra_calls():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(hours=2)).isoformat())
    row["player1"] = {"id": "11"}
    row["player2"] = {"id": "22"}

    unrelated = _event("999")
    unrelated["homeTeam"] = {"id": "11"}
    unrelated["awayTeam"] = {"id": "33"}
    target = _event("101", winner_code=2)
    target["homeTeam"] = {"id": "11"}
    target["awayTeam"] = {"id": "22"}

    # Simulate the production cap where one near lookup is available for one
    # due row. The first run can only inspect player1 and persists rotation.
    first_provider = _NearFallbackProvider({"11": unrelated, "22": target})
    first = scan_match_statuses(
        {"upcoming": [row]}, first_provider,
        {"preferred_route": "near"}, now=now, max_checks=1, max_near_checks=1,
    )
    assert first_provider.near_calls == ["11"]
    assert first["statuses"] == {}
    assert first["pending"]["101"]["n"] == "2"

    # The next scheduled run spends the same single near call on player2 and
    # resolves the tracked event. No per-run API ceiling increase is required.
    second_provider = _NearFallbackProvider({"11": unrelated, "22": target})
    second = scan_match_statuses(
        {"upcoming": [row]}, second_provider, first,
        now=now+timedelta(minutes=30), max_checks=1, max_near_checks=1,
    )
    assert second_provider.near_calls == ["22"]
    assert second["statuses"]["101"]["status"] == "loss"
    assert second["newly_resolved"] == 1
    assert second["provider_requests"] == 2  # live + one near


def test_legacy_checked_pending_starts_with_second_player_under_tight_near_cap():
    now = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(hours=2)).isoformat())
    row["player1"] = {"id": "11"}
    row["player2"] = {"id": "22"}
    target = _event("101", winner_code=2)
    target["homeTeam"] = {"id": "11"}
    target["awayTeam"] = {"id": "22"}
    provider = _NearFallbackProvider({"22": target})
    previous = {
        "preferred_route": "near",
        "pending": {
            "101": {
                "t": row["scheduled_at"], "s": "11", "a": "11", "b": "22",
                "c": (now-timedelta(minutes=30)).isoformat(), "p": "1",
            }
        },
    }
    snapshot = scan_match_statuses(
        {"upcoming": [row]}, provider, previous,
        now=now, max_checks=1, max_near_checks=1,
    )
    assert provider.near_calls == ["22"]
    assert snapshot["statuses"]["101"]["status"] == "loss"


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


def test_all_unfinished_past_start_matches_are_eligible_without_any_time_window():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    old_today = _row("old", "11", (now-timedelta(hours=5)).isoformat())
    recent = _row("recent", "11", (now-timedelta(hours=1)).isoformat())
    yesterday = _row("yesterday", "11", (now-timedelta(hours=30)).isoformat())
    last_week = _row("last_week", "11", (now-timedelta(days=8)).isoformat())
    future = _row("future", "11", (now+timedelta(hours=2)).isoformat())
    same_time = _row("now", "11", now.isoformat())
    provider = _Provider()
    result = scan_match_statuses(
        {"upcoming": [old_today, recent, yesterday, last_week, future, same_time]},
        provider, now=now, max_checks=30,
    )
    assert result["due"] == 4
    assert result["checked"] == 4
    assert result["pending_count"] == 4
    assert result["window_candidates"] == 4
    assert "future" not in result["pending"]
    assert "now" not in result["pending"]


def test_seventy_unfinished_matches_continue_thirty_at_a_time():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    rows = []
    for i in range(70):
        row = _row(
            str(1000+i), str(2000+i),
            (now-timedelta(hours=70-i)).isoformat(),
        )
        row["player1"]["id"] = str(2000+i)
        rows.append(row)
    first = scan_match_statuses({"upcoming": rows}, _Provider(), now=now)
    assert first["due"] == 70
    assert first["checked"] == 30
    assert first["pending_count"] == 70
    assert first["next_due_id"] == "1030"
    second_provider = _Provider()
    second = scan_match_statuses(
        {"upcoming": rows}, second_provider, first, now=now+timedelta(hours=1),
    )
    assert second["checked"] == 30
    assert second_provider.previous_calls[0][0] == "2030"
    assert second["next_due_id"] == "1060"
    third_provider = _Provider()
    third = scan_match_statuses(
        {"upcoming": rows}, third_provider, second, now=now+timedelta(hours=2),
    )
    assert third["checked"] == 30
    assert third_provider.previous_calls[0][0] == "2060"
    assert third["next_due_id"] == "1020"


def test_thirty_two_completed_matches_are_settled_across_two_hourly_runs():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    rows, finished = [], {}
    for i in range(32):
        row = _row(
            str(1000+i), str(2000+i), (now-timedelta(hours=1)).isoformat(),
        )
        row["player1"]["id"] = str(2000+i)
        rows.append(row)
        event = _event(str(1000+i))
        event["homeTeam"]["id"] = str(2000+i)
        finished[str(2000+i)] = [event]
    feed = {"upcoming": rows}
    first = scan_match_statuses(feed, _Provider(previous=finished), now=now)
    assert first["checked"] == 30
    assert first["newly_resolved"] == 30
    assert first["pending_count"] == 2
    second = scan_match_statuses(
        feed, _Provider(previous=finished), first, now=now+timedelta(hours=1),
    )
    assert second["due"] == 2
    assert second["checked"] == 2
    assert second["newly_resolved"] == 2
    assert second["terminal"] == 32
    assert second["pending_count"] == 0


def test_started_is_provisional_and_does_not_prevent_followup():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(hours=4)).isoformat())
    previous = {"statuses": {"101": {"status": "started", "checked_at": now.isoformat()}}}
    result = scan_match_statuses(
        {"upcoming": [row]}, _Provider(previous={"11": [_event()]}),
        previous, now=now,
    )
    assert result["statuses"]["101"]["status"] == "win"
    assert result["newly_resolved"] == 1


def test_verified_cancelation_sets_void_and_ends_checking():
    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    row = _row("101", "11", (now-timedelta(hours=1)).isoformat())
    canceled = _event(status_type="canceled", description="Canceled", winner_code=0)
    provider = _Provider(previous={"11": [canceled]})
    first = scan_match_statuses({"upcoming": [row]}, provider, now=now)
    assert first["statuses"]["101"]["status"] == "void"
    second = scan_match_statuses({"upcoming": [row]}, _Provider(), first, now=now)
    assert second["checked"] == 0


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
    assert morning["due"] == 1
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


def test_production_worker_tracks_only_current_0600_betting_day_rows():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    before_six_local = _row("old-day", "11", "2026-10-02T01:10:00+00:00")
    current = _row("current-day", "11", "2026-10-02T08:00:00+00:00")
    provider = _Provider()

    result = scan_match_statuses(
        {"top_daily_picks": [before_six_local, current]},
        provider,
        now=now,
        max_checks=20,
    )

    assert result["tracked"] == 1
    assert result["due"] == 1
    assert set(result["pending"]) == {"current-day"}
    assert provider.previous_calls == [("11", 0)]


def test_production_worker_drops_prior_day_pending_and_terminal_snapshot_rows():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    current = _row("current-day", "11", "2026-10-02T08:00:00+00:00")
    previous = {
        "pending": {
            "old-day": {
                "t": "2026-10-02T01:10:00+00:00",
                "s": "11", "a": "11", "b": "22", "c": "", "p": "1",
            }
        },
        "statuses": {
            "old-finished": {"status": "win", "checked_at": "2026-10-02T02:00:00+00:00"},
        },
    }

    result = scan_match_statuses(
        {"top_daily_picks": [current]},
        _Provider(),
        previous,
        now=now,
        max_checks=20,
    )

    assert "old-day" not in result["pending"]
    assert "old-finished" not in result["statuses"]
    assert set(result["pending"]) == {"current-day"}


def test_match_status_accepts_external_24_7_scheduler():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/match-status.yml").read_text()
    assert "  schedule:" not in workflow
    assert "timezone:" not in workflow
    assert "workflow_dispatch:" in workflow


def test_settled_event_exposes_match_and_second_set_outcome_for_radar_results():
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    event = _event("101", winner_code=1)
    event["homeScore"] = {"period1": 4, "period2": 6, "period3": 6}
    event["awayScore"] = {"period1": 6, "period2": 3, "period3": 2}
    provider = _Provider(previous={"11": [event]})
    result = scan_match_statuses(
        {"upcoming": [_row("101", "11", (now-timedelta(hours=3)).isoformat())]},
        provider, now=now,
    )
    assert result["settled_events"] == [{
        "event_id": "101",
        "match_status": "win",
        "second_set_status": "win",
        "checked_at": now.isoformat(),
    }]


def test_time_budget_resumes_first_unchecked_event(monkeypatch):
    from tbt.services import match_status as module

    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class SlowProvider(_Provider):
        def live_events(self):
            clock[0] += 4.0
            return []

        def previous_player_matches(self, player_id, page=0):
            clock[0] += 5.0
            return super().previous_player_matches(player_id, page)

    feed = {"upcoming": [
        _row("101", scheduled_at=(now-timedelta(hours=2)).isoformat()),
        _row("202", scheduled_at=(now-timedelta(hours=1)).isoformat()),
    ]}
    first = SlowProvider()
    result = scan_match_statuses(feed, first, now=now, max_wall_seconds=12)
    assert first.previous_calls == [("11", 0)]
    assert result["checked"] == 1
    assert result["next_due_id"] == "202"
    assert result["pending_count"] == 2
    assert result["time_budget_exhausted"] is True

    clock[0] = 0.0
    second = SlowProvider()
    continued = scan_match_statuses(
        feed, second, result, now=now+timedelta(hours=1), max_wall_seconds=12,
    )
    assert second.previous_calls == [("11", 0)]
    assert continued["next_due_id"] == "101"


def test_slow_404_skips_near_fallback_when_deadline_is_too_close(monkeypatch):
    from tbt.errors import ProviderError
    from tbt.services import match_status as module

    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class Slow404Provider(_NearFallbackProvider):
        def live_events(self):
            return []

        def previous_player_matches(self, player_id, page=0):
            clock[0] += 18.0
            raise ProviderError("RapidAPI HTTP 404 for previous route")

    provider = Slow404Provider()
    feed = {"upcoming": [_row(scheduled_at=(now-timedelta(hours=1)).isoformat())]}
    result = scan_match_statuses(feed, provider, now=now, max_wall_seconds=22)
    assert provider.near_calls == []
    assert result["time_budget_exhausted"] is True
    # The only due item remains pending, without fabricating any match outcome.
    assert result["pending_count"] == 1
    assert result["statuses"] == {}


def test_short_retry_budget_never_sleeps_on_provider_429_or_500(monkeypatch):
    import httpx
    import pytest
    from types import SimpleNamespace
    from tbt.errors import ProviderError
    from tbt.providers import rapidapi

    for status in (429, 500):
        called = []
        client = rapidapi.RapidTennisClient.__new__(rapidapi.RapidTennisClient)
        client.cfg = SimpleNamespace(
            rapidapi_base_url="https://provider.invalid",
            rapidapi_key="test",
            rapidapi_host="provider.invalid",
        )
        client.client = httpx.Client(transport=httpx.MockTransport(
            lambda request: (called.append(request) or httpx.Response(
                status, headers={"Retry-After": "3600"}))
        ))
        client._last_request_at = 0.0
        client.request_count = 0
        client.request_limit = 8
        client.rate_limit_remaining = None
        client.request_budget = None
        client.retry_attempts = 1
        monkeypatch.setattr(
            rapidapi.time, "sleep",
            lambda seconds: (_ for _ in ()).throw(
                AssertionError("worker must not sleep on its last attempt")),
        )
        try:
            with pytest.raises(ProviderError, match=f"HTTP {status}"):
                client._get("/api/tennis/events/live")
            assert client.request_count == 1
            assert len(called) == 1
        finally:
            client.close()


def test_runtime_deadline_stops_before_next_provider_lookup(monkeypatch):
    from tbt.services import match_status as module

    now = datetime(2026, 9, 25, 7, 30, tzinfo=timezone.utc)
    rows = [
        _row("101", "11", (now-timedelta(hours=2)).isoformat()),
        _row("102", "11", (now-timedelta(hours=1)).isoformat()),
    ]
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class SlowProvider(_Provider):
        def previous_player_matches(self, player_id, page=0):
            clock[0] += 8.0
            return super().previous_player_matches(player_id, page)

    provider = SlowProvider()
    result = scan_match_statuses(
        {"upcoming": rows}, provider, now=now,
        max_checks=30, max_wall_seconds=12.0,
    )
    assert result["runtime_limited"] is True
    assert result["time_budget_exhausted"] is True
    assert result["checked"] == 1
    assert provider.previous_calls == [("11", 0)]
    assert result["next_due_id"] == "102"
    assert result["pending_count"] == 2


def test_runtime_provider_fast_fail_configuration_is_bounded():
    from tbt.providers.rapidapi import RapidTennisClient
    from tbt.config import Settings

    cfg = Settings(rapidapi_key="test")
    client = RapidTennisClient(cfg)
    try:
        client.configure_runtime_fast_fail(timeout_seconds=4, attempts=1)
        assert client.retry_attempts == 1
        assert client.client.timeout.read == 4.0
    finally:
        client.close()


def test_runtime_status_overlay_adds_only_match_winner_results_and_dedupes_aliases():
    row = _row("101", "11", "2026-09-29T12:00:00+00:00")
    row["betting"] = {"selection_id": "11", "odds": 1.62}
    row["market_publications"] = [
        {
            "issued_at": "2026-09-29T06:00:00+00:00",
            "publication_status": "published",
            "section": "top_daily",
            "market": "match_winner",
            "selection_id": "11",
            "odds": 1.62,
            "result": None,
        },
        {
            "issued_at": "2026-09-29T06:00:00+00:00",
            "publication_status": "published",
            "section": "ace",
            "market": "aces",
            "selection_id": "11",
            "odds": 1.66,
            "result": None,
        },
    ]
    feed = {
        "daily_picks": [row],
        "top_daily_picks": [dict(row)],
        "results": [],
    }
    rows = runtime_settled_results(feed, {
        "101": {
            "status": "win",
            "checked_at": "2026-09-29T15:30:00+00:00",
        }
    })
    assert len(rows) == 1
    assert rows[0]["runtime_result_overlay"] is True
    assert len(rows[0]["market_publications"]) == 1
    publication = rows[0]["market_publications"][0]
    assert publication["market"] == "match_winner"
    assert publication["result"]["correct"] is True
    assert publication["result"]["runtime_source"] == "match_status_snapshot"
    assert publication["result"]["staked_units"] == 1.0
    assert abs(publication["result"]["profit_units"] - .62) < 1e-12



def test_top200_is_tracked_and_runtime_settled_like_other_match_winner_sections():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    row = _row("top200-1", "11", (now-timedelta(hours=2)).isoformat())
    row["betting"] = {"selection_id": "11", "odds": 1.55, "betting_day": "2026-10-02"}
    row["market_publications"] = [{
        "issued_at": "2026-10-02T06:00:00+00:00",
        "publication_status": "published",
        "section": "top200",
        "market": "match_winner",
        "selection_id": "11",
        "odds": 1.55,
        "betting_day": "2026-10-02",
        "result": None,
    }]
    event = _event("top200-1", winner_code=1)
    provider = _Provider(previous={"11": [event]})

    snapshot = scan_match_statuses(
        {"top200_picks": [row]},
        provider,
        now=now,
        max_checks=5,
    )
    assert snapshot["tracked"] == 1
    assert snapshot["due"] == 1
    assert snapshot["statuses"]["top200-1"]["status"] == "win"

    settled = runtime_settled_results(
        {"top200_picks": [row], "results": []},
        snapshot["statuses"],
    )
    assert len(settled) == 1
    publication = settled[0]["market_publications"][0]
    assert publication["section"] == "top200"
    assert publication["result"]["correct"] is True
    assert publication["result"]["runtime_source"] == "match_status_snapshot"
    assert abs(publication["result"]["profit_units"] - .55) < 1e-12


def test_runtime_status_overlay_settles_deployed_daily_row_without_embedded_publication():
    row = _row("deployed-1", "11", "2026-10-02T12:00:00+00:00")
    row.update({
        "betting_day": "2026-10-02",
        "publication_status": "pending",
        "issued_at": None,
        "market": "match_winner",
        "selection": "Alpha",
        "odds": 1.62,
        "betting": {
            "market": "match_winner",
            "selection_id": "11",
            "selection": "Alpha",
            "odds": 1.62,
            "model_probability": .68,
            "betting_day": "2026-10-02",
        },
    })

    rows = runtime_settled_results(
        {"top_daily_picks": [row], "results": []},
        {
            "deployed-1": {
                "status": "win",
                "checked_at": "2026-10-02T15:00:00+00:00",
            }
        },
    )

    assert len(rows) == 1
    assert rows[0]["runtime_result_overlay"] is True
    publication = rows[0]["market_publications"][0]
    assert publication["section"] == "top_daily"
    assert publication["market"] == "match_winner"
    assert publication["selection_id"] == "11"
    assert publication["odds"] == 1.62
    assert publication["runtime_publication_evidence"] == "deployed_daily_offer_row"
    assert not publication.get("issued_at")
    assert publication["result"]["correct"] is True
    assert publication["result"]["runtime_source"] == "match_status_snapshot"
    assert abs(publication["result"]["profit_units"] - .62) < 1e-12


def test_runtime_status_overlay_derives_each_deployed_match_winner_section():
    source_sections = {
        "top200_picks": "top200",
        "top_daily_picks": "top_daily",
        "prime_picks": "prime",
        "value_picks": "value",
        "doubles_picks": "doubles",
    }
    feed = {"results": []}
    statuses = {}
    for index, (source, section) in enumerate(source_sections.items(), start=1):
        event_id = f"deployed-{index}"
        player1 = f"p{index}"
        player2 = f"q{index}"
        row = _row(event_id, player1, "2026-10-02T12:00:00+00:00")
        row["player1"]["id"] = player1
        row["player2"]["id"] = player2
        row["winner_id"] = player1
        row["betting"] = {
            "market": "match_winner",
            "selection_id": player1,
            "odds": 1.50 + index / 100,
            "betting_day": "2026-10-02",
        }
        feed[source] = [row]
        statuses[event_id] = {
            "status": "win",
            "checked_at": "2026-10-02T15:00:00+00:00",
        }

    rows = runtime_settled_results(feed, statuses)
    assert len(rows) == len(source_sections)
    assert {
        row["market_publications"][0]["section"]
        for row in rows
    } == set(source_sections.values())
    assert all(
        row["market_publications"][0]["result"]["runtime_source"]
        == "match_status_snapshot"
        for row in rows
    )


def test_runtime_status_overlay_keeps_roi_fail_closed_without_real_odds():
    row = _row("202", "11", "2026-09-29T13:00:00+00:00")
    row["market_publications"] = [{
        "issued_at": "2026-09-29T06:00:00+00:00",
        "publication_status": "published",
        "section": "value",
        "market": "match_winner",
        "selection_id": "11",
        "odds": None,
        "result": None,
    }]
    rows = runtime_settled_results(
        {"value_picks": [row], "results": []},
        {"202": {"status": "loss", "checked_at": "2026-09-29T15:00:00+00:00"}},
    )
    result = rows[0]["market_publications"][0]["result"]
    assert result["correct"] is False
    assert result["status"] == "miss"
    assert "staked_units" not in result
    assert "profit_units" not in result


def test_runtime_status_overlay_never_replaces_existing_durable_result():
    row = _row("303", "11", "2026-09-29T14:00:00+00:00")
    publication = {
        "issued_at": "2026-09-29T06:00:00+00:00",
        "publication_status": "published",
        "section": "top_daily",
        "market": "match_winner",
        "selection_id": "11",
        "odds": 1.70,
        "result": {
            "status": "hit",
            "correct": True,
            "staked_units": 1.0,
            "profit_units": .70,
        },
    }
    row["market_publications"] = [publication]
    rows = runtime_settled_results(
        {"daily_picks": [row], "results": [row]},
        {"303": {"status": "loss", "checked_at": "2026-09-29T15:00:00+00:00"}},
    )
    assert len(rows) == 1
    assert rows[0]["market_publications"][0]["result"]["correct"] is True
    assert "runtime_overlay" not in rows[0]["market_publications"][0]["result"]


def test_feed_wires_runtime_status_only_after_results_entitlement():
    source = (Path(__file__).resolve().parents[1] / "api" / "function_app.py").read_text()
    block = source.split('def feed(req):', 1)[1].split('def _membership_allowed', 1)[0]
    assert 'if bool(entitlements.get("results")):' in block
    assert 'runtime_settled_results(data, data["match_statuses"])' in block


def test_large_backlog_prioritizes_current_betting_day_without_more_requests():
    now = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)
    old_rows = []
    for i in range(105):
        player_id = str(2000 + i)
        row = _row(
            f"old-{i}", player_id,
            (now - timedelta(days=1, hours=2) + timedelta(minutes=i)).isoformat(),
        )
        row["player1"]["id"] = player_id
        row["player2"]["id"] = str(5000 + i)
        old_rows.append(row)

    recent_rows = []
    for i in range(5):
        player_id = str(9000 + i)
        row = _row(
            f"today-{i}", player_id,
            (now - timedelta(hours=4) + timedelta(minutes=i * 10)).isoformat(),
        )
        row["player1"]["id"] = player_id
        row["player2"]["id"] = str(9500 + i)
        recent_rows.append(row)

    provider = _Provider()
    result = scan_match_statuses(
        {"upcoming": old_rows + recent_rows},
        provider,
        now=now,
        max_checks=5,
        max_near_checks=5,
    )

    assert result["priority_mode"] is True
    assert result["current_betting_day_due"] == 5
    assert result["backlog_due"] == 105
    assert result["checked"] == 5
    assert provider.previous_calls[:4] == [
        ("9000", 0), ("9001", 0), ("9002", 0), ("9003", 0),
    ]
    assert provider.previous_calls[4] == ("2000", 0)
    # Request budget is unchanged: one LIVE lookup plus five history lookups.
    assert result["provider_requests"] == 6


def test_shared_budget_exhaustion_is_safe_pause_without_provider_calls():
    now = datetime(2026, 10, 1, 2, 30, tzinfo=timezone.utc)

    class SharedBudgetExhausted(Exception):
        pass

    class BudgetPausedProvider(_Provider):
        def __init__(self):
            super().__init__()
            self.request_count = 0

        def live_events(self):
            raise SharedBudgetExhausted("shared daily budget exhausted")

        def previous_player_matches(self, player_id, page=0):
            raise AssertionError("history lookup must not run after shared budget pause")

    row = _row("budget-1", "11", (now - timedelta(hours=1)).isoformat())
    provider = BudgetPausedProvider()
    result = scan_match_statuses(
        {"upcoming": [row]},
        provider,
        now=now,
        max_checks=5,
        max_near_checks=5,
    )

    assert result["budget_paused"] is True
    assert result["degraded"] is False
    assert result["provider_requests"] == 0
    assert result["checked"] == 0
    assert result["provider_errors"] == {"SharedBudgetExhausted": 1}
    assert result["pending_count"] == 1
    # A single pending fixture needs no rotation cursor; it is naturally first
    # on the next run and must simply remain unresolved.
    assert result["next_due_id"] == ""
    assert result["statuses"] == {}


def test_match_status_worker_returns_200_for_budget_pause_before_generic_degraded_error():
    source = (
        Path(__file__).resolve().parents[1] / "api" / "function_app.py"
    ).read_text(encoding="utf-8")
    block = source.split(
        'def internal_match_status_worker(req):', 1
    )[1].split(
        '@app.route(route="v1/internal/account-inactivity-worker"', 1
    )[0]
    budget_branch = 'if saved.get("budget_paused"):'
    degraded_branch = 'if saved.get("degraded"):'
    assert budget_branch in block
    assert degraded_branch in block
    assert block.index(budget_branch) < block.index(degraded_branch)
    assert '"shared_budget_exhausted_safe_skip"' in block
    assert '"match_status_provider_unavailable"' in block


def test_match_status_worker_uses_higher_bounded_throughput():
    source = (
        Path(__file__).resolve().parents[1] / "api" / "function_app.py"
    ).read_text(encoding="utf-8")
    block = source.split(
        'def internal_match_status_worker(req):', 1
    )[1].split(
        '@app.route(route="v1/internal/account-inactivity-worker"', 1
    )[0]
    assert 'client.request_limit = 24' in block
    assert 'BLINQ_MATCH_STATUS_MAX_CHECKS", "20"' in block
    assert 'min(20, int(os.getenv("BLINQ_MATCH_STATUS_MAX_CHECKS"' in block
    assert 'max_near_checks=20' in block
    assert 'max_wall_seconds=22.0' in block
    assert 'reserve_shared_api_budget("match")' in block


def test_production_status_queue_ignores_generic_upcoming_board():
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    generic = [
        _row(
            f"board-{i}", "11",
            (now - timedelta(hours=1, minutes=i)).isoformat(),
        )
        for i in range(100)
    ]
    top = _row("top-1", "11", (now - timedelta(hours=1)).isoformat())
    prime = _row("prime-1", "11", (now - timedelta(hours=2)).isoformat())
    value = _row("value-1", "11", (now - timedelta(hours=3)).isoformat())
    doubles = _row("doubles-1", "11", (now - timedelta(hours=4)).isoformat())
    feed = {
        "upcoming": generic,
        "top_daily_picks": [top],
        "prime_picks": [prime],
        "value_picks": [value],
        "doubles_picks": [doubles],
    }

    result = scan_match_statuses(feed, _Provider(), now=now, max_checks=20)

    assert result["tracked"] == 4
    assert result["due"] == 4
    assert result["pending_count"] == 4
    assert result["checked"] == 4
    assert not any(key.startswith("board-") for key in result["pending"])


def test_legacy_unmarked_pending_backlog_is_dropped_on_public_feed():
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    previous = {
        "pending": {
            "legacy-board": {
                "t": (now - timedelta(hours=3)).isoformat(),
                "s": "11", "a": "11", "b": "22", "c": "",
            }
        }
    }
    feed = {
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
    }

    result = scan_match_statuses(feed, _Provider(), previous, now=now)

    assert result["tracked"] == 0
    assert result["due"] == 0
    assert result["pending_count"] == 0


def test_public_pending_is_not_carried_across_betting_day_rollover():
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    previous = {
        "pending": {
            "recent-public": {
                "t": (now - timedelta(hours=30)).isoformat(),
                "s": "11", "a": "11", "b": "22", "c": "", "p": "1",
            },
            "stale-public": {
                "t": (now - timedelta(hours=60)).isoformat(),
                "s": "11", "a": "11", "b": "22", "c": "", "p": "1",
            },
        }
    }
    feed = {
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
    }

    result = scan_match_statuses(feed, _Provider(), previous, now=now, max_checks=20)

    assert result["tracked"] == 0
    assert result["due"] == 0
    assert result["pending_count"] == 0
    assert "recent-public" not in result["pending"]
    assert "stale-public" not in result["pending"]


def test_inprogress_winner_code_must_not_finalize_match():
    """The provider may expose winnerCode before the final whistle."""
    live = _event(winner_code=1, status_type="inprogress", description="2nd set")
    assert classify_finished_event(_row(), live) is None


def test_rechecks_premature_live_terminal_snapshot():
    """A false terminal win from a previous worker must not be sticky."""
    now = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now - timedelta(hours=3)).isoformat())
    previous = {"statuses": {"101": {
        "status": "win", "winner_id": "11",
        "provider_status": "inprogress 2nd set",
        "checked_at": (now-timedelta(hours=2)).isoformat(),
    }}}
    final = _event("101", winner_code=2, status_type="finished", description="Ended")
    client = _Provider(live=[final])
    snapshot = scan_match_statuses({"upcoming": [row]}, client, previous, now=now)
    assert snapshot["newly_resolved"] == 1
    assert snapshot["statuses"]["101"]["status"] == "loss"
    assert snapshot["statuses"]["101"]["provider_status"] == "finished ended"
    assert snapshot["pending_count"] == 0
    assert client.previous_calls == []


def test_ongoing_match_remains_pending_after_quarantining_false_terminal():
    now = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)
    row = _row("101", "11", (now - timedelta(hours=3)).isoformat())
    previous = {"statuses": {"101": {
        "status": "win", "winner_id": "11",
        "provider_status": "inprogress 2nd set",
    }}}
    ongoing = _event("101", winner_code=1, status_type="inprogress", description="2nd set")
    client = _Provider(live=[ongoing])
    snapshot = scan_match_statuses({"upcoming": [row]}, client, previous, now=now)
    assert snapshot["terminal"] == 0
    assert snapshot["newly_resolved"] == 0
    assert snapshot["pending_count"] == 1
    assert snapshot["due"] == 1
