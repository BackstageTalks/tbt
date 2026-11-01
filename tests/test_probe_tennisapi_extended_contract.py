"""Offline checks for the guarded read-only extended TennisApi probe."""
from scripts.probe_tennisapi_extended_contract import _nested_int, run_probe, summarize


class StubClient:
    def __init__(self):
        self.request_count = 0
        self.rate_limit_remaining = 14000
        self.request_limit = None
        self.retry_attempts = None
        self.paths = []

    def _get(self, path, params=None, *, enrichment=False):
        assert enrichment is True
        assert self.request_limit is not None
        assert self.request_count < self.request_limit
        self.request_count += 1
        self.paths.append((path, params))
        if path == "/api/tennis/event/14494928":
            return {"event": {
                "id": 14494928, "season": {"id": 12345},
                "homeTeam": {"id": 222},
                "tournament": {"uniqueTournament": {"id": 333}}}}
        if path.endswith("/odds/1/all"):
            return {"eventId": 14494928, "markets": [
                {"marketId": 1, "marketName": "Full time", "suspended": False},
                {"marketId": 13, "marketName": "Tie break in match", "suspended": True},
            ]}
        return {}


def test_positive_ids_only():
    assert _nested_int({"season": {"id": "123"}}, "season", "id") == 123
    assert _nested_int({"season": {"id": True}}, "season", "id") is None
    assert _nested_int({"season": {"id": -1}}, "season", "id") is None


def test_live_probe_resolves_ids_and_does_not_write_data():
    client = StubClient()
    report = run_probe(client, event_id=14494928, max_requests=24)
    assert report["eligible_for_cdb_import"] is False
    assert report["provider_quote_timestamp_verified"] is False
    assert report["request_count"] <= 24
    assert [p for p, _ in client.paths[:3]] == [
        "/api/tennis/event/14494928",
        "/api/tennis/event/14494928/statistics",
        "/api/tennis/event/14494928/point-by-point",
    ]
    assert report["resolved_context"] == {
        "event_id_matched": True,
        "season_id": 12345, "tournament_id": 333, "player_id": 222,
    }
    assert any("/api/odds/season/12345/provider/1/all" == p for p, _ in client.paths)
    assert any("/api/tennis/player/222/events/previous/0" == p for p, _ in client.paths)
    assert any("/api/tennis/player/222/events/last/0" == p for p, _ in client.paths)
    assert report["observations"]["event_odds"]["market_ids"] == {"1": 1, "13": 1}
    assert report["observations"]["event_odds"]["suspended_markets"] == 1


def test_probe_is_hard_bounded_even_when_context_is_available():
    client = StubClient()
    report = run_probe(client, event_id=14494928, max_requests=5)
    assert report["request_count"] == 5
    assert len(client.paths) == 5
    assert report["observations"]["event_detail"]["state"] == "available"
    assert report["observations"]["daily_categories"]["state"] == "budget_cap"
    assert all("payload" not in o for o in report["observations"].values()
               if o["state"] == "budget_cap")


def test_suspended_and_aces_market_observed_without_becoming_cdb_value():
    info = summarize("event_odds", {
        "markets": [{"marketId": 17, "marketName": "Player aces",
                     "suspended": True,
                     "choices": [{"name": "Over"}, {"name": "Under"}]}],
        "eventId": 4,
    }, event_id=4)
    assert info["has_aces_ou"] is True
    assert info["suspended_markets"] == 1
    assert info["quote_timestamp_present"] is False


def test_shared_budget_exhaustion_halts_subsequent_calls():
    class RequestBudgetExceeded(Exception):
        pass

    class ExhaustedClient(StubClient):
        def _get(self, path, params=None, *, enrichment=False):
            self.request_count += 1
            raise RequestBudgetExceeded("provider reserve reached")

    client = ExhaustedClient()
    report = run_probe(client, event_id=14494928, max_requests=24)
    assert client.request_count == 1
    assert report["observations"]["event_detail"]["error_type"] == (
        "RequestBudgetExceeded")
    assert report["observations"]["odds_providers_sk_web"]["state"] == (
        "shared_budget_guard_halted")

def test_phased_metadata_and_odds_have_separate_guarded_calls():
    metadata = StubClient()
    report = run_probe(metadata, event_id=14494928, max_requests=6,
                       phase="metadata")
    assert report["phase"] == "metadata"
    assert report["request_count"] == 6
    assert report["eligible_for_cdb_import"] is False
    assert report["identity_validated_for_import"] is False
    assert metadata.paths[0][0] == (
        "/api/tennis/tournament/2449/season/67287/rounds")
    assert not any("/api/odds/" in p for p, _ in metadata.paths)
    odds = StubClient()
    result = run_probe(odds, event_id=14494928, max_requests=3, phase="odds")
    assert result["request_count"] == 3
    assert odds.paths[0][0] == "/api/tennis/event/14494928/odds/1/all"
    assert odds.paths[1][0] == "/api/odds/season/67287/provider/1/all"
    assert odds.paths[2][0] == "/api/odds/providers/SK/web-odds"


def test_phased_double_examples_stay_research_only():
    client = StubClient()
    report = run_probe(client, event_id=14494928, max_requests=8,
                       phase="doubles")
    assert report["request_count"] == 2
    assert report["identity_validated_for_import"] is False
    assert report["eligible_for_cdb_import"] is False
    assert client.paths == [
        ("/api/tennis/team/39234/players", None),
        ("/api/tennis/team/69208/year-statistics/2025", None),
    ]


def test_phased_budget_termination_remains_fail_closed():
    class RequestBudgetExceeded(Exception):
        pass
    class Blocked(StubClient):
        def _get(self, path, params=None, *, enrichment=False):
            self.request_count += 1
            raise RequestBudgetExceeded("Provider rate-limit remaining header missing")
    client = Blocked()
    report = run_probe(client, event_id=14494928, max_requests=10,
                       phase="metadata")
    assert report["request_count"] == 1
    assert report["observations"]["tournament_rounds"]["reason_code"] == (
        "missing_provider_header")
    assert report["observations"]["player_rankings"]["state"] == (
        "shared_budget_guard_halted")


def test_phased_unknown_request_is_rejected_before_api_calls():
    client = StubClient()
    import pytest
    with pytest.raises(ValueError, match="phase"):
        run_probe(client, event_id=14494928, max_requests=1, phase="other")
    assert client.request_count == 0

def test_targeted_case_runs_only_preapproved_route():
    client = StubClient()
    result = run_probe(client, event_id=14494928, max_requests=10,
                       phase="odds", case="season_odds")
    assert result["request_count"] == 1
    assert result["case"] == "season_odds"
    assert client.paths == [
        ("/api/odds/season/67287/provider/1/all", None),
    ]


def test_targeted_case_cannot_call_undeclared_endpoint():
    import pytest
    client = StubClient()
    with pytest.raises(ValueError, match="allowlist"):
        run_probe(client, event_id=14494928, max_requests=10,
                  phase="odds", case="../../api/live")
    assert client.request_count == 0

def test_historical_coverage_routes_are_exact_and_budgeted():
    historical = StubClient()
    result = run_probe(historical, event_id=14494928, max_requests=3,
                       phase="historical")
    assert result["request_count"] == 3
    assert historical.paths == [
        ("/api/tennis/team/69208/year-statistics/2024", None),
        ("/api/tennis/team/69208/year-statistics/2022", None),
        ("/api/tennis/team/69208/year-statistics/2020", None),
    ]
    assert result["eligible_for_cdb_import"] is False
    assert result["identity_validated_for_import"] is False


def test_historical_quality_counts_without_exposing_values():
    payload = {"statistics": [
        {"aces": 4, "firstServePointsScored": 11,
         "firstServePointsTotal": 14, "breakPointsScored": 4,
         "breakPointsTotal": 3},
        {"aces": None, "firstServePointsScored": None,
         "firstServePointsTotal": 0},
    ]}
    result = summarize("year_stats_2024", payload, event_id=1)
    assert result["season_stat_groups"] == 2
    assert result["non_null_fields"]["aces"] == 1
    assert result["non_null_fields"]["firstServePointsTotal"] == 2
    assert result["statistic_pairs_compared"] == 2
    assert result["statistic_bound_violations"] == 1
    assert result["point_in_time_match_eligibility"] is False
    assert "11" not in str(result["collections"])


def test_player_doc_example_identity_is_research_not_cdb_link():
    client = StubClient()
    report = run_probe(client, event_id=14494928, max_requests=2,
                       phase="identity")
    assert report["request_count"] == 2
    assert report["identity_validated_for_import"] is False
    assert client.paths == [
        ("/api/tennis/player/69208", None),
        ("/api/tennis/team/69208", None),
    ]

def test_archive_2016_selects_provider_native_finished_event():
    class Historical(StubClient):
        def _get(self, path, params=None, *, enrichment=False):
            self.request_count += 1
            self.paths.append((path, params))
            if path == "/api/tennis/calendar/10/7/2016/categories":
                return {"categories": [{"id": -100, "name": "Grand Slam"}]}
            if path == "/api/tennis/category/-100/events/10/7/2016":
                return {"events": [
                    {"id": 900, "homeTeam": {"id": 4},
                     "awayTeam": {"id": 5}, "status": {"type": "finished"},
                     "tournament": {"name": "Other"}},
                    {"id": 800, "homeTeam": {"id": 31},
                     "awayTeam": {"id": 32}, "status": {"type": "finished"},
                     "tournament": {"name": "Wimbledon"}},
                    {"id": 700, "homeTeam": {"id": 3, "name": "A / B"},
                     "awayTeam": {"id": 4}, "status": {"type": "finished"},
                     "tournament": {"name": "Wimbledon Doubles"}},
                    {"id": 100, "homeTeam": {"id": 1},
                     "awayTeam": {"id": 2}, "status": {"type": "inprogress"},
                     "tournament": {"name": "Wimbledon"}},
                ]}
            return {"statistics": []}

    client = Historical()
    report = run_probe(client, event_id=14494928, max_requests=4,
                       phase="archive_2016")
    assert report["historical_sample_event_id"] == 800
    assert report["historical_sample_policy"] == "wimbledon_finished"
    assert report["historical_source_home_id"] == 31
    assert report["archived_category_count"] == 1
    assert report["request_count"] == 4
    assert client.paths == [
        ("/api/tennis/calendar/10/7/2016/categories", None),
        ("/api/tennis/category/-100/events/10/7/2016", None),
        ("/api/tennis/event/800/statistics", None),
        ("/api/tennis/event/800/point-by-point", None),
    ]
    assert report["observations"]["historical_2016_player_year_stats"]["state"] == "budget_cap"
    assert report["eligible_for_cdb_import"] is False
    assert report["identity_validated_for_import"] is False


def test_archive_2016_empty_category_day_never_invents_a_match_id():
    class Empty(StubClient):
        def _get(self, path, params=None, *, enrichment=False):
            self.request_count += 1
            self.paths.append((path, params))
            if path == "/api/tennis/calendar/10/7/2016/categories":
                return {"categories": [{"id": -100, "name": "Grand Slam"}]}
            return {"events": []}
    client = Empty()
    result = run_probe(client, event_id=14494928, max_requests=4,
                       phase="archive_2016")
    assert result["request_count"] == 2
    assert result["historical_sample_policy"] == "no_valid_completed_event"
    assert "historical_sample_event_id" not in result


def test_archive_2016_no_calendar_coverage_is_not_2016_no_matches():
    class Unsupported(StubClient):
        def _get(self, path, params=None, *, enrichment=False):
            self.request_count += 1
            self.paths.append((path, params))
            return {}  # Provider HTTP 204 normalized by client
    client = Unsupported()
    result = run_probe(client, event_id=14494928, max_requests=4,
                       phase="archive_2016")
    assert result["request_count"] == 1
    assert result["historical_sample_policy"] == "category_calendar_unavailable"
    assert "historical_sample_event_id" not in result
    assert all("/api/tennis/events/" not in p for p, _ in client.paths)


def test_archive_2016_missing_grand_slam_category_does_not_guess_id():
    class OtherCategory(StubClient):
        def _get(self, path, params=None, *, enrichment=False):
            self.request_count += 1
            self.paths.append((path, params))
            return {"categories": [{"id": 3, "name": "ATP"}]}
    client = OtherCategory()
    result = run_probe(client, event_id=14494928, max_requests=4,
                       phase="archive_2016")
    assert result["historical_sample_policy"] == "grand_slam_category_missing"
    assert result["request_count"] == 1
    assert "historical_sample_event_id" not in result


def test_archive_2016_rejects_custom_case():
    import pytest
    with pytest.raises(ValueError, match="case"):
        run_probe(StubClient(), event_id=14494928, max_requests=4,
                  phase="archive_2016", case="arbitrary")
