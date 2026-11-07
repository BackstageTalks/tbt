"""Offline contracts for source-native, quota-guarded TennisApi bulk/odds probes."""
from datetime import datetime, timezone

import pytest

from scripts.probe_tennisapi_extended_contract import run_probe


WITNESS = 17449516
STAMP = int(datetime(2026, 9, 11, 14, tzinfo=timezone.utc).timestamp())


class Stub:
    def __init__(self, *, valid=True):
        self.valid = valid
        self.request_count = 0
        self.rate_limit_remaining = 14000
        self.request_limit = None
        self.retry_attempts = 4
        self.paths = []

    def _get(self, path, params=None, *, enrichment=False):
        assert enrichment is True
        assert self.retry_attempts == 1
        assert self.request_limit is not None
        assert self.request_count < self.request_limit
        self.request_count += 1
        self.paths.append(path)
        if path == f"/api/tennis/event/{WITNESS}":
            return {"event": {
                "id": WITNESS if self.valid else WITNESS + 1,
                "homeTeam": {"id": 123456}, "awayTeam": {"id": 654321},
                "season": {"id": 82442},
                "tournament": {"uniqueTournament": {"id": 2404}},
                "startTimestamp": STAMP,
            }}
        if path.endswith("/events/last/0"):
            return {"events": [{"id": WITNESS}, {"id": WITNESS}]}
        if path.endswith("/winning-odds"):
            return {}  # HTTP 204 is represented as {} by the real provider client.
        if "/odds/featured/" in path:
            return {"events": [{"id": WITNESS}]}
        return {"events": []}


def test_bulk_probes_all_documented_routes_with_one_source_witness():
    stub = Stub()
    report = run_probe(stub, event_id=WITNESS, max_requests=16, phase="bulk")
    assert report["bulk_state"] == "tested"
    assert report["bulk_source_event_id_matched"] is True
    assert report["bulk_endpoint_observations"] == 14
    assert report["request_count"] == 15 == len(stub.paths)
    assert len(set(stub.paths)) == 15
    assert stub.paths[:2] == [
        f"/api/tennis/event/{WITNESS}",
        "/api/tennis/tournament/2404/season/82442/events/last/0",
    ]
    assert "/api/tennis/tournament/2404/schedules/11/9/2026" in stub.paths
    assert "/api/tennis/player/123456/events/09/2026" in stub.paths
    assert "/api/tennis/team/123456/events/09/2026" in stub.paths
    assert "/api/tennis/event/17449516/provider/1/winning-odds" in stub.paths
    assert "/api/tennis/event/17449516/odds" in stub.paths
    assert "/api/tennis/events/odds/featured/1" in stub.paths
    assert "/api/tennis/events/odds/11/9/2026" in stub.paths
    assert "/api/tennis/calendar/9/2026" in stub.paths
    assert "/api/tennis/scheduled-tournaments/11/9/2026/page/1" in stub.paths
    assert "/api/event/newly-added" in stub.paths
    assert "/api/tennis/tournament/2404/season/82442/rounds" in stub.paths
    assert "/api/tennis/tournament/2404/season/82442/cup-trees" in stub.paths
    assert "/api/tennis/tournament/2363/season/48186/events/round/32/slug/round-of-64" in stub.paths
    assert report["observations"]["tournament_round_documented_example"][
        "query_provenance"] == "independent_documented_example_2023"
    assert report["observations"]["tournament_last_matches"][
        "duplicate_native_event_ids"] == 1
    assert report["observations"]["match_winning_odds"]["state"] == "no_content"
    assert report["eligible_for_cdb_import"] is False
    assert report["provider_quote_timestamp_verified"] is False
    assert report["cdb_writes"] == report["model_changes"] == 0
    assert report["observations"]["featured_tennis_odds"][
        "point_in_time_odds_verified"] is False


def test_no_provider_expense_after_bad_source_witness():
    stub = Stub(valid=False)
    report = run_probe(stub, event_id=WITNESS, max_requests=16, phase="bulk")
    assert report["bulk_state"] == "invalid_source_witness"
    assert report["bulk_source_event_id_matched"] is False
    assert report["request_count"] == 1
    assert len(stub.paths) == 1
    assert report["eligible_for_cdb_import"] is False


def test_strict_provider_budget_cap_and_no_undeclared_calls():
    stub = Stub()
    report = run_probe(stub, event_id=WITNESS, max_requests=5, phase="bulk")
    assert report["request_count"] == len(stub.paths) == 5
    assert report["observations"]["featured_tennis_odds"]["state"] == "budget_cap"
    assert report["bulk_endpoint_observations"] == 14
    assert report["eligible_for_cdb_import"] is False


@pytest.mark.parametrize("max_requests, case", [
    (1, None), (17, None), (16, "win_odds"), (0, None),
])
def test_invalid_bulk_contract_stops_before_call(max_requests, case):
    stub = Stub()
    with pytest.raises(ValueError):
        run_probe(stub, event_id=WITNESS, max_requests=max_requests,
                  phase="bulk", case=case)
    assert stub.request_count == 0


def test_source_timestamp_unknown_disables_bulk():
    class UnknownStamp(Stub):
        def _get(self, path, params=None, *, enrichment=False):
            result = super()._get(path, params, enrichment=enrichment)
            if path.endswith(f"/{WITNESS}"):
                result["event"]["startTimestamp"] = None
            return result

    stub = UnknownStamp()
    report = run_probe(stub, event_id=WITNESS, max_requests=16, phase="bulk")
    assert report["request_count"] == 1
    assert report["bulk_state"] == "invalid_source_witness"
