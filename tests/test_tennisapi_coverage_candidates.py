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
    assert client.player_singles_results("222", 0) == {"source": "mock"}
    assert calls == [
        ("/api/tennis/team/222/year-statistics/2024", True),
        ("/api/tennis/tournament/2363/season/55443/events/last/0", True),
        ("/api/tennis/player/222/events/singles/last/0", True),
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
    with pytest.raises(ValueError):
        client.player_singles_results(bad)


def test_research_routes_reject_future_year_and_negative_page():
    client = object.__new__(RapidTennisClient)
    client._get = lambda *args, **kwargs: pytest.fail("Should not call provider")
    with pytest.raises(ValueError):
        client.team_year_statistics(222, 9999)
    with pytest.raises(ValueError):
        client.tournament_season_last_matches(2363, 55443, page=-1)
    with pytest.raises(ValueError):
        client.player_singles_results(222, page=-1)


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
                {"matches": 6, "groundType": "Grass", "aces": 8,
                 "totalServeAttempts": 610, "firstServeTotal": 444,
                 "secondServeTotal": 166, "doubleFaults": 12,
                 "firstServePointsScored": 170, "firstServePointsTotal": 278,
                 "secondServePointsScored": 79, "secondServePointsTotal": 154,
                 "breakPointsScored": 18, "breakPointsTotal": 48,
                 "opponentBreakPointsScored": 24, "opponentBreakPointsTotal": 48},
                {"matches": 6, "groundType": "Hardcourt indoor", "aces": 8,
                 "totalServeAttempts": 559, "firstServeTotal": 459,
                 "secondServeTotal": 100, "doubleFaults": 8,
                 "firstServePointsScored": 198, "firstServePointsTotal": 359,
                 "secondServePointsScored": 49, "secondServePointsTotal": 92,
                 "breakPointsScored": 18, "breakPointsTotal": 35,
                 "opponentBreakPointsScored": 26, "opponentBreakPointsTotal": 52},
            ]}
        if path.endswith("/events/last/0"):
            return {"events": [
                {"id": 7, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
                 "startTimestamp": 1700000000},
                {"id": 8, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
                 "startTimestamp": 1700000100},
            ]}
        return {"events": [
            {"id": 5, "homeTeam": {"id": 222}, "awayTeam": {"id": 333},
             "startTimestamp": 1700000000}
        ]}


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
    assert report["candidate_state"] == "endpoint_available"
    assert report["candidate_context"]["source_event_id_matched"] is True
    assert report["candidate_context"]["identity_validated_for_import"] is False
    assert report["candidate_context"]["point_in_time_verified"] is False
    assert report["eligible_for_cdb_import"] is False
    assert report["provider_quote_timestamp_verified"] is False
    assert report["observations"]["candidate_" + case]["state"] == "available"
    if case == "player_singles_results":
        inventory = report["observations"]["candidate_player_singles_results"]
        assert inventory["source_player_match_rows"] == 1
        assert inventory["missing_participant_identity_rows"] == 0
        assert inventory["identical_participant_identity_rows"] == 0
        assert inventory["unrelated_participant_rows"] == 0


def test_year_statistics_inventory_is_aggregate_not_match_cells():
    client = CandidateClient()
    result = run_probe(client, event_id=98765, max_requests=2,
                       phase="candidates", case="team_year_statistics")
    stats = result["observations"]["candidate_team_year_statistics"]
    assert stats["season_stat_groups"] == 2
    assert stats["total_matches"] == 12
    assert stats["distinct_surfaces"] == 2
    assert stats["groups_with_positive_matches"] == 2
    assert stats["service_identity_checks"] == 6
    assert stats["service_identity_violations"] == 0
    assert stats["statistic_bound_violations"] == 0
    assert stats["non_null_fields"]["firstServePointsTotal"] == 2
    assert stats["point_in_time_match_eligibility"] is False
    assert "Test P1" not in str(stats)
    assert "firstServePointsScored': 10" not in str(stats)


def test_last_matches_inventory_never_asserts_complete_season():
    report = run_probe(CandidateClient(), event_id=98765, max_requests=2,
                       phase="candidates", case="tournament_last_matches")
    info = report["observations"]["candidate_tournament_last_matches"]
    assert info["event_rows"] == 2
    assert info["distinct_event_ids"] == 2
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


def test_candidate_empty_response_is_no_coverage_not_success():
    class NoCoverage(CandidateClient):
        def _get(self, path, params=None, *, enrichment=False):
            if path == "/api/tennis/event/98765":
                return super()._get(path, params=params, enrichment=enrichment)
            assert self.request_count < self.request_limit
            self.request_count += 1
            self.paths.append(path)
            return {}

    client = NoCoverage()
    report = run_probe(client, event_id=98765, max_requests=2,
                       phase="candidates", case="team_year_statistics")
    assert report["request_count"] == 2
    assert report["candidate_state"] == "endpoint_no_content"
    assert report["observations"]["candidate_team_year_statistics"]["state"] == (
        "no_content")
    assert report["eligible_for_cdb_import"] is False


def test_candidate_blocked_provider_does_not_bypass_budget_guard():
    class RequestBudgetExceeded(Exception):
        pass

    class Blocked(CandidateClient):
        def _get(self, path, params=None, *, enrichment=False):
            if path == "/api/tennis/event/98765":
                return super()._get(path, params=params, enrichment=enrichment)
            self.request_count += 1
            self.paths.append(path)
            raise RequestBudgetExceeded("Provider reserve reached")

    client = Blocked()
    report = run_probe(client, event_id=98765, max_requests=2,
                       phase="candidates", case="tournament_last_matches")
    assert report["request_count"] == 2
    assert report["candidate_state"] == "endpoint_error"
    assert report["observations"]["candidate_tournament_last_matches"]["reason_code"] == (
        "provider_reserve_reached")
    assert report["eligible_for_cdb_import"] is False


def test_zero_rows_or_unrecognized_candidate_envelopes_not_coverage():
    for case in ("team_year_statistics", "tournament_last_matches",
                 "player_singles_results"):
        class Empty(CandidateClient):
            def _get(self, path, params=None, *, enrichment=False):
                if path == "/api/tennis/event/98765":
                    return super()._get(path, params=params, enrichment=enrichment)
                self.request_count += 1
                self.paths.append(path)
                return {"statistics": []} if case == "team_year_statistics" else {"events": []}

        result = run_probe(Empty(), event_id=98765, max_requests=2,
                           phase="candidates", case=case)
        assert result["candidate_state"] == "endpoint_no_content"
        assert result["eligible_for_cdb_import"] is False

        class BadEnvelope(Empty):
            def _get(self, path, params=None, *, enrichment=False):
                if path == "/api/tennis/event/98765":
                    return super()._get(path, params=params, enrichment=enrichment)
                self.request_count += 1
                self.paths.append(path)
                return {"unexpected": "not-usable"}

        result = run_probe(BadEnvelope(), event_id=98765, max_requests=2,
                           phase="candidates", case=case)
        assert result["candidate_state"] == "endpoint_unrecognized_shape"


def test_duplicate_season_page_is_not_valid_coverage():
    class Duplicate(CandidateClient):
        def _get(self, path, params=None, *, enrichment=False):
            if path == "/api/tennis/event/98765":
                return super()._get(path, params=params, enrichment=enrichment)
            self.request_count += 1
            self.paths.append(path)
            return {"events": [
                {"id": 7, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
                 "startTimestamp": 1700000000},
                {"id": 7, "homeTeam": {"id": 1}, "awayTeam": {"id": 2},
                 "startTimestamp": 1700000100},
            ]}

    report = run_probe(Duplicate(), event_id=98765, max_requests=2,
                       phase="candidates", case="tournament_last_matches")
    assert report["candidate_state"] == "endpoint_invalid_shape"
    assert report["observations"]["candidate_tournament_last_matches"]["distinct_event_ids"] == 1
    assert report["eligible_for_cdb_import"] is False


def test_inconsistent_service_arithmetic_is_quarantined_not_accepted():
    class BadService(CandidateClient):
        def _get(self, path, params=None, *, enrichment=False):
            response = super()._get(path, params=params, enrichment=enrichment)
            if path.endswith("/year-statistics/2024"):
                response["statistics"][0]["totalServeAttempts"] = 609
            return response

    report = run_probe(BadService(), event_id=98765, max_requests=2,
                       phase="candidates", case="team_year_statistics")
    assert report["candidate_state"] == "endpoint_invalid_statistics"
    assert report["observations"]["candidate_team_year_statistics"][
        "service_identity_violations"] == 1
    assert report["eligible_for_cdb_import"] is False


def test_duplicate_surface_breakpoints_and_zero_matches_are_rejected():
    for issue in ("surface", "breakpoints", "matches"):
        class BadStats(CandidateClient):
            def _get(self, path, params=None, *, enrichment=False):
                response = super()._get(path, params=params, enrichment=enrichment)
                if path.endswith("/year-statistics/2024"):
                    if issue == "surface":
                        response["statistics"][1]["groundType"] = "Grass"
                    elif issue == "breakpoints":
                        response["statistics"][1]["breakPointsScored"] = 999
                    else:
                        response["statistics"][1]["matches"] = 0
                return response

        report = run_probe(BadStats(), event_id=98765, max_requests=2,
                           phase="candidates", case="team_year_statistics")
        assert report["candidate_state"] == "endpoint_invalid_statistics"
        assert report["eligible_for_cdb_import"] is False


def test_singles_requires_unique_dated_matches_not_just_http_success():
    for kind in ("duplicate", "missing_date"):
        class InvalidSingles(CandidateClient):
            def _get(self, path, params=None, *, enrichment=False):
                response = super()._get(path, params=params, enrichment=enrichment)
                if path.endswith("/events/singles/last/0"):
                    if kind == "duplicate":
                        response["events"].append(dict(response["events"][0]))
                    else:
                        response["events"][0].pop("startTimestamp")
                return response

        report = run_probe(InvalidSingles(), event_id=98765, max_requests=2,
                           phase="candidates", case="player_singles_results")
        assert report["candidate_state"] == "endpoint_invalid_shape"
        assert report["eligible_for_cdb_import"] is False


@pytest.mark.parametrize("bad_case", ["unrelated", "same_player", "missing_player_id"])
def test_singles_requires_exact_source_player_in_every_match(bad_case):
    class WrongPlayer(CandidateClient):
        def _get(self, path, params=None, *, enrichment=False):
            payload = super()._get(path, params=params, enrichment=enrichment)
            if path.endswith("/events/singles/last/0"):
                event = payload["events"][0]
                if bad_case == "unrelated":
                    event["homeTeam"]["id"] = 999
                elif bad_case == "same_player":
                    event["awayTeam"]["id"] = 222
                else:
                    event["homeTeam"].pop("id")
            return payload

    report = run_probe(WrongPlayer(), event_id=98765, max_requests=2,
                       phase="candidates", case="player_singles_results")
    assert report["request_count"] == 2
    assert report["candidate_state"] == "endpoint_invalid_identity"
    assert report["eligible_for_cdb_import"] is False
    inventory = report["observations"]["candidate_player_singles_results"]
    expected = {
        "unrelated": "unrelated_participant_rows",
        "same_player": "identical_participant_identity_rows",
        "missing_player_id": "missing_participant_identity_rows",
    }[bad_case]
    assert inventory["source_player_match_rows"] == 0
    assert inventory[expected] == 1
