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
