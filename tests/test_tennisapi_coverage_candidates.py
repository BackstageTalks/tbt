"""Offline contracts for research-only TennisApi season endpoint candidates."""
from datetime import datetime, timezone

import pytest

from scripts.probe_tennisapi_extended_contract import run_probe, summarize
from tbt.providers.rapidapi import RapidTennisClient


def test_research_client_uses_only_guarded_native_routes():
    client = object.__new__(RapidTennisClient)
    calls = []

    def fake_get(path, *, enrichment=False):
        calls.append((path, enrichment))
        return {"source": "mock"}

    client._get = fake_get
    assert client.team_year_statistics("222", 2024) == {"source": "mock"}
    assert client.tournament_season_last_matches(2363, "55443", page=0) == {
        "source": "mock"}
    assert calls == [
        ("/api/tennis/team/222/year-statistics/2024", True),
        ("/api/tennis/tournament/2363/season/55443/events/last/0", True),
    ]


@pytest.mark.parametrize("bad", [None, -1, 0, True, False, 2.5,
                                  "12/other", "1?key=x", " 1 ", ""])
def test_research_routes_reject_invalid_ids_without_requests(bad):
    client = object.__new__(RapidTennisClient)
    client._get = lambda *args, **kwargs: pytest.fail("Should not call provider")
    with pytest.raises(ValueError):
        client.team_year_statistics(bad, 2024)
    with pytest.raises(ValueError):
        client.tournament_season_last_matches(bad, 100)
    with pytest.raises(ValueError):
        client.tournament_season_last_matches(100, bad)


def test_research_routes_reject_future_year_and_negative_page():
    client = object.__new__(RapidTennisClient)
    client._get = lambda *args, **kwargs: pytest.fail("Should not call provider")
    with pytest.raises(ValueError):
        client.team_year_statistics(222, 9999)
    with pytest.raises(ValueError):
        client.tournament_season_last_matches(2363, 55443, page=-1)


class CandidateClient:
    def __init__(self, *, mismatch=False, missing_season=False):
        self.request_count = 0
        self.rate_limit_remaining = 14400
        self.request_limit = None
        self.retry_attempts = None
        self.paths = []
        self.mismatch = mismatch
        self.missing_season = missing_season

    def _get(self, path, params=None, *, enrichment=False):
        assert enrichment is True
        assert self.request_count < self.request_limit
        self.request_count += 1
        self.paths.append(path)
        if path == "/api/tennis/event/98765":
            event = {
                "id": 999 if self.mismatch else 98765,
                "homeTeam": {"id": 222, "name": "Test P1"},
                "awayTeam": {"id": 333, "name": "Test P2"},
                "tournament": {"uniqueTournament": {"id": 2363}},
                "startTimestamp": int(datetime(2024, 1, 28,
                                               tzinfo=timezone.utc).timestamp()),
            }
            if not self.missing_season:
                event["season"] = {"id": 55443}
            return {"event": event}
        if path.endswith("/year-statistics/2024"):
            return {"statistics": [
                {"aces": 4, "firstServePointsScored": 10,
                 "firstServePointsTotal": 20},
            ]}
        if path.endswith("/events/last/0"):
            return {"events": [
                {"id": 7, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
                 "startTimestamp": 1700000000},
                {"id": 7, "homeTeam": {"id": 1}, "awayTeam": {"id": 2}},
            ]}
        return {"events": [{"id": 5}]}


@pytest.mark.parametrize("case,route", [
    ("team_year_statistics", "/api/tennis/team/222/year-statistics/2024"),
    ("tournament_last_matches",
     "/api/tennis/tournament/2363/season/55443/events/last/0"),
    ("player_singles_results", "/api/tennis/player/222/events/singles/last/0"),
])
def test_candidate_research_resolves_source_ids_and_spends_two_calls(case, route):
    client = CandidateClient()
    report = run_probe(client, event_id=98765, max_requests=2,
                       phase="candidates", case=case)
    assert client.paths == ["/api/tennis/event/98765", route]
    assert report["request_count"] == 2
    assert report["candidate_state"] == "response_recorded_research_only"
    assert report["candidate_context"]["source_event_id_matched"] is True
    assert report["candidate_context"]["identity_validated_for_import"] is False
    assert report["candidate_context"]["point_in_time_verified"] is False
    assert report["eligible_for_cdb_import"] is False
    assert report["provider_quote_timestamp_verified"] is False
    assert report["observations"]["candidate_" + case]["state"] == "available"


def test_year_statistics_inventory_is_aggregate_not_match_cells():
    client = CandidateClient()
    result = run_probe(client, event_id=98765, max_requests=2,
                       phase="candidates", case="team_year_statistics")
    stats = result["observations"]["candidate_team_year_statistics"]
    assert stats["season_stat_groups"] == 1
    assert stats["statistic_bound_violations"] == 0
    assert stats["non_null_fields"]["firstServePointsTotal"] == 1
    assert stats["point_in_time_match_eligibility"] is False
    assert "Test P1" not in str(stats)
    assert "firstServePointsScored': 10" not in str(stats)


def test_last_matches_inventory_never_asserts_complete_season():
    report = run_probe(CandidateClient(), event_id=98765, max_requests=2,
                       phase="candidates", case="tournament_last_matches")
    info = report["observations"]["candidate_tournament_last_matches"]
    assert info["event_rows"] == 2
    assert info["distinct_event_ids"] == 1
    assert info["rows_with_two_players"] == 2
    assert info["completeness_verified"] is False


def test_invalid_case_fails_before_provider_calls():
    for case in (None, "unknown", "../../api"):
        client = CandidateClient()
        with pytest.raises(ValueError, match="preapproved case"):
            run_probe(client, event_id=98765, max_requests=2,
                      phase="candidates", case=case)
        assert client.paths == []


def test_missing_or_mismatched_context_fails_closed_without_second_call():
    for client, case, state in [
        (CandidateClient(mismatch=True), "team_year_statistics",
         "unavailable_or_mismatched_event"),
        (CandidateClient(missing_season=True), "tournament_last_matches",
         "missing_tournament_or_season"),
    ]:
        result = run_probe(client, event_id=98765, max_requests=2,
                           phase="candidates", case=case)
        assert client.paths == ["/api/tennis/event/98765"]
        assert result["request_count"] == 1
        assert result["candidate_state"] == state
        assert result["eligible_for_cdb_import"] is False


def test_one_request_limit_stops_before_optional_endpoint():
    client = CandidateClient()
    report = run_probe(client, event_id=98765, max_requests=1,
                       phase="candidates", case="team_year_statistics")
    assert client.paths == ["/api/tennis/event/98765"]
    assert report["request_count"] == 1
    assert report["observations"]["candidate_team_year_statistics"]["state"] == (
        "budget_cap")
    assert report["eligible_for_cdb_import"] is False
