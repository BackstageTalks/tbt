"""Offline contract for one-time 3 Nov Telegram ACE result archival."""
from copy import deepcopy
import pytest

from tbt.services.telegram_20261103_recovery import (
    ISSUED_ACES, _candidate_rows, _frozen_status_witness, DAY, HALYS, recover,
)


DATA = {
    "17475617": ("289146", "286492", 11, 3, "win"),
    "17453204": ("289106", "204330", 6, 0, "win"),
    "17428202": ("385485", "95935", 6, 5, "win"),
    "17479726": ("16311", "339453", 0, 6, "win"),
    "17452315": ("221410", "327924", None, None, "void"),
    "17475619": ("309071", "135778", 8, 1, "win"),
    "17446377": ("411652", "112747", 1, 6, "win"),
    "17477378": ("371456", "215802", 1, 8, "loss"),
}


def fixture():
    statuses, event_details = {}, {}
    for eid, selected, name, start, line, prediction, odds, count in ISSUED_ACES:
        if eid == HALYS:
            event_details[eid] = {"event": {
                "id": 17449516, "startTimestamp": 1793700000,
                "status": {"type": "finished"}, "winnerCode": 1,
                "homeTeam": {"id": 90798, "name": "Quentin Halys"},
                "awayTeam": {"id": 321789, "name": "Arthur Fery"},
                "tournament": {"name": "Paris, France", "category": {"id": 3}},
            }}
            continue
        p1, p2, aces1, aces2, state = DATA[eid]
        event_details[eid] = {"event": {
            "id": int(eid), "status": {"type": "canceled" if state == "void" else "finished"},
            "homeTeam": {"id": int(p1), "name": name if selected == p1 else "Opposition One"},
            "awayTeam": {"id": int(p2), "name": name if selected == p2 else "Opposition Two"},
            "tournament": {"name": "Other Tennis", "category": {"id": 3}},
        }}
        status = {
            "status": state, "provider_home_id": p1, "provider_away_id": p2,
            "checked_at": "2026-11-03T19:30:43+00:00",
            "provider_status": "canceled canceled" if state == "void" else "finished ended",
        }
        if count is not None:
            status.update({
                "projection_stats_p1_id": p1, "projection_stats_p2_id": p2,
                "projection_stats": {"p1_aces": aces1, "p2_aces": aces2},
            })
        statuses[eid] = status
    halys_stats = {"statistics": [
        {"period": "ALL", "groups": [{"statisticsItems": [
            {"key": "aces", "home": "17", "away": "8"}
        ]}]}
    ]}
    return {"statuses": statuses}, event_details, halys_stats


def test_pinned_3nov_aces_are_all_graded_by_existing_native_archive_writer():
    snapshot, details, stats = fixture()
    candidates = _candidate_rows(
        snapshot, details, stats, "2026-11-04T07:40:00+00:00")
    assert len(candidates) == 9
    assert {row["event_id"] for row in candidates} == {row[0] for row in ISSUED_ACES}
    result = [row["market_publications"][0]["result"] for row in candidates]
    assert sum(r.get("correct") is True for r in result) == 5
    assert sum(r.get("correct") is False for r in result) == 3
    assert sum(r.get("void") is True for r in result) == 1
    assert all(r["runtime_source"] == "match_status_snapshot" for r in result)
    for row in candidates:
        assert row["betting_day"] == DAY
        pub = row["market_publications"][0]
        assert pub["price_contract"] == "player_total_ou"
        assert pub["issued_at"] < row["scheduled_at"]


def test_wrong_event_id_never_creates_a_historical_result():
    snap, details, stats = fixture()
    details[HALYS]["event"]["id"] += 1
    with pytest.raises(ValueError, match="identity"):
        _candidate_rows(snap, details, stats, "2026-11-04T07:40:00+00:00")


def test_wrong_player_or_wrong_original_stats_cannot_be_graded():
    snap, details, stats = fixture()
    snap["statuses"]["17475617"]["provider_home_id"] = "999999"
    with pytest.raises(ValueError, match="participant"):
        _candidate_rows(snap, details, stats, "2026-11-04T07:40:00+00:00")
    snap, details, stats = fixture()
    snap["statuses"]["17475617"]["projection_stats"]["p1_aces"] = 12
    with pytest.raises(ValueError, match="actual ACE"):
        _candidate_rows(snap, details, stats, "2026-11-04T07:40:00+00:00")


def test_halys_requires_exact_source_native_count_and_verified_status():
    snap, details, stats = fixture()
    stats["statistics"][0]["groups"][0]["statisticsItems"][0]["home"] = "16"
    with pytest.raises(ValueError, match="source-native"):
        _candidate_rows(snap, details, stats, "2026-11-04T07:40:00+00:00")
    snap, details, stats = fixture()
    details[HALYS]["event"]["status"]["type"] = "inprogress"
    with pytest.raises(ValueError, match="Halys"):
        _candidate_rows(snap, details, stats, "2026-11-04T07:40:00+00:00")


def test_original_void_is_never_inferred_as_aces_loss():
    snap, details, stats = fixture()
    snap["statuses"]["17452315"]["provider_status"] = "finished ended"
    with pytest.raises(ValueError, match="cancellation"):
        _candidate_rows(snap, details, stats, "2026-11-04T07:40:00+00:00")


def test_frozen_source_statuses_cover_exactly_eight_issuer_verified_fixtures():
    witness = _frozen_status_witness()
    assert set(witness['statuses']) == {eid for eid, *_ in ISSUED_ACES if eid != HALYS}
    assert witness['statuses']['17475617']['projection_stats']['p1_aces'] == 11
    assert witness['statuses']['17446377']['projection_stats']['p2_aces'] == 6
    assert witness['statuses']['17452315']['provider_status'] == 'canceled canceled'
