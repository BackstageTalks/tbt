"""Offline positive and fail-closed source -> canonical native-ID overlap tests."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.audit_tennisapi_bulk_cdb_yield import (
    canonical_index, exact_link, native_id_claims, run,
)


def dt(iso):
    return datetime.fromisoformat(iso)


def match(eid, day, *, home=11, away=22, winner=11, tour="atp", mid="canonical"):
    return SimpleNamespace(
        match_id=mid, tour=tour,
        scheduled_at=dt(day),
        player1_id=str(home), player2_id=str(away),
        winner_id=str(winner), stats={},
        provider_payload={"_tbt_event_identity": {
            "event_id": str(eid), "home": str(home), "away": str(away),
            "status": "finished",
        }}
    )


def event(eid, stamp, home=11, away=22, *, tour="atp", tid=2363):
    return {
        "id": eid, "startTimestamp": int(dt(stamp).timestamp()),
        "homeTeam": {"id": home, "type": 1},
        "awayTeam": {"id": away, "type": 1},
        "tournament": {
            "category": {"slug": tour},
            "uniqueTournament": {"id": tid},
        },
        "season": {"id": 48186 if tour == "atp" else 77777},
        "status": {"type": "finished"}, "winnerCode": 1,
        "homeScore": {"current": 2}, "awayScore": {"current": 0},
    }


class Stub:
    def __init__(self, bad_witness=False):
        self.bad_witness = bad_witness
        self.request_count = 0
        self.request_limit = 14500
        self.retry_attempts = 5
        self.rate_limit_remaining = 10000
        self.paths = []
        self.client = SimpleNamespace(event_hooks={"response": []})

    def _get(self, path, *, enrichment=False):
        assert enrichment is True and self.retry_attempts == 1
        assert self.request_count < self.request_limit
        self.request_count += 1
        self.paths.append(path)
        if path == "/api/tennis/event/17449516":
            e = event(17449516, "2026-09-11T12:00:00+00:00",
                      home=33, away=44, tour="wta", tid=2404)
            e["season"]["id"] = 80000
            if self.bad_witness:
                e["id"] += 1
            return {"event": e}
        if path.endswith("round/32/slug/round-of-64"):
            return {"events": [event(100, "2023-01-18T12:00:00+00:00")]}
        if "season/48186/events/last/0" in path:
            return {"events": [event(100, "2023-01-18T12:00:00+00:00")]}
        if "schedules/18/1/2023" in path:
            return {"events": [event(100, "2023-01-18T12:00:00+00:00"),
                               event(101, "2023-01-18T12:00:00+00:00",
                                     home=55, away=66)]}
        if path.endswith("events/last/0") or "/schedules/11/9/2026" in path:
            return {"events": [event(17449516, "2026-09-11T12:00:00+00:00",
                                     home=33, away=44, tour="wta", tid=2404)]}
        if "/player/33/events/09/2026" in path:
            return {"events": [event(17449516, "2026-09-11T12:00:00+00:00",
                                     home=33, away=44, tour="wta", tid=2404)]}
        if "/events/odds/11/9/2026" in path:
            return {"odds": {"17449516": {"marketId": 1},
                             "999999": {"marketId": 1}}}
        if path.endswith("/winning-odds"):
            return {"home": {"fractionalValue": "1/2"},
                    "away": {"fractionalValue": "2/1"}}
        if path.endswith("/odds/1/all"):
            return {"markets": [{"marketId": 1}]}
        return {}


def test_exact_match_requires_id_pair_day_tour_and_winner():
    m = match(100, "2023-01-18T12:00:00+00:00")
    idx, _ = canonical_index([m])
    row = dict(event_id=100, home_id=11, away_id=22,
               utc_day="2023-01-18", tour="atp", winner_id=11)
    assert exact_link(row, idx)[0] == "linked_exact_native_id_pair_date_tour_winner"
    for key, value in (
        ("home_id", 99), ("utc_day", "2023-01-17"),
        ("tour", "wta"), ("winner_id", 22)):
        altered = dict(row, **{key: value})
        assert exact_link(altered, idx)[0] == "identity_conflict"
    assert exact_link(dict(row, event_id=9999), idx)[0] == "unlinked_source_id"


def test_collision_ambiguity_and_claim_conflict_quarantined():
    a = match(100, "2023-01-18T12:00:00+00:00", mid="a")
    b = match(100, "2023-01-18T12:00:00+00:00", mid="b")
    idx, _ = canonical_index([a, b])
    row = {"event_id":100}
    assert exact_link(row, idx)[0] == "ambiguous_canonical_native_id"
    b.provider_payload["_tbt_statistics"] = {"event_id": "101"}
    assert len(native_id_claims(b)) == 2
    idx, metrics = canonical_index([a, b])
    assert metrics["canonical_conflicting_native_claim_rows"] == 1
    assert len(idx[100]) == 1
    with pytest.raises(ValueError, match="duplicated"):
        canonical_index([a, a])


def test_10_call_live_plan_is_readonly_and_dedups_across_routes():
    rows = [
        match(100, "2023-01-18T12:00:00+00:00", mid="a"),
        match(17449516, "2026-09-11T12:00:00+00:00",
              home=33, away=44, winner=33, tour="wta", mid="b"),
    ]
    provider = Stub()
    report = run(provider, rows, max_requests=12)
    assert report["provider_requests_including_retries"] == 10 == len(provider.paths)
    assert report["source"]["unique_eligible_native_event_ids"] == 3
    assert report["source"]["status_counts"][
        "linked_exact_native_id_pair_date_tour_winner"] == 2
    assert report["source"]["status_counts"]["unlinked_source_id"] == 1
    assert report["source"]["validation_counts"]["same_event_across_routes"] >= 2
    assert report["endpoint"]["2026_daily_odds"]["raw_native_keys"] == 2
    assert report["endpoint"]["2026_daily_odds"]["native_keys_in_cdb"] == 1
    assert report["endpoint"]["2026_daily_odds"]["bulk_pair_intake"][
        "counts"]["native_events_with_parseable_pair"] == 0
    assert report["verified_net_new_cdb_matches"] == 0
    assert report["verified_net_new_cdb_statistic_values"] == 0
    assert report["verified_historical_prematch_odds"] == 0
    assert report["cdb_writes"] == report["model_changes"] == 0


def test_budget_bounds_and_bad_source_witness_stop_new_paid_calls():
    p=Stub(bad_witness=True)
    with pytest.raises(ValueError,match="witness mismatched"):
        run(p, [], max_requests=12)
    assert p.request_count == 4
    with pytest.raises(ValueError,match="1..12"):
        run(Stub(), [], max_requests=13)


class BulkPairStub(Stub):
    def _get(self, path, *, enrichment=False):
        if path == "/api/tennis/events/odds/11/9/2026":
            assert enrichment is True and self.retry_attempts == 1
            self.request_count += 1
            self.paths.append(path)
            return {"odds": {
                str(17449516 if i == 0 else 500000 + i): {
                    "choices": [
                        {"name": "1", "fractionalValue": "3/2"},
                        {"name": "2", "fractionalValue": "2/3"},
                    ],
                } for i in range(994)
            }}
        return super()._get(path, enrichment=enrichment)


def test_existing_10_call_cdb_overlap_audit_parses_all_994_without_extra_requests():
    rows = [
        match(100, "2023-01-18T12:00:00+00:00", mid="a"),
        match(17449516, "2026-09-11T12:00:00+00:00",
              home=33, away=44, winner=33, tour="wta", mid="b"),
    ]
    p = BulkPairStub()
    report = run(p, rows, max_requests=12)
    assert p.request_count == 10 == len(p.paths)
    odds = report["endpoint"]["2026_daily_odds"]
    assert odds["raw_native_keys"] == 994
    assert odds["bulk_pair_intake"]["counts"]["parseable_two_sided_pairs"] == 994
    assert odds["candidate_native_events_with_single_cdb_claim"] == 1
    assert odds["candidate_native_events_without_cdb_claim"] == 993
    assert odds["candidate_native_events_with_ambiguous_cdb_claim"] == 0
    assert odds["candidate_identity_verified_against_cdb"] == 0
    assert odds["validated_historical_quote_pairs"] == 0
    assert odds["cdb_odds_writes"] == 0
    assert odds["bulk_pair_intake"]["cdb_writes"] == 0
    assert report["verified_historical_prematch_odds"] == report["cdb_writes"] == 0
    import json
    encoded = json.dumps(report, sort_keys=True)
    assert '"source_event_id"' not in encoded
    assert '"latest_decimal"' not in encoded
    assert "3/2" not in encoded
    assert '"500001"' not in encoded
