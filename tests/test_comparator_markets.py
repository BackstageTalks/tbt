from datetime import datetime, timedelta, timezone

from tbt.schemas import MatchRecord
from tbt.services.comparator_markets import build_market_state, project_market_state

CUTOFF = datetime(2026, 11, 1, tzinfo=timezone.utc)


def match(day, tour="atp", *, aces_a=7, aces_b=4, status="completed"):
    return MatchRecord(
        match_id=f"{tour}-{day}-{status}",
        tour=tour,
        scheduled_at=CUTOFF - timedelta(days=day),
        player1_id="a", player1_name="Alpha One",
        player2_id="b", player2_name="Beta Two",
        surface="hard", winner_id="a", status=status, best_of=3,
        stats={
            "p1_aces": aces_a, "p2_aces": aces_b,
            "p1_double_faults": 2, "p2_double_faults": 3,
        },
    )


def project(state, left="atp:a", right="atp:b", tour="atp"):
    return project_market_state(
        state, left_key=left, right_key=right, tour=tour,
        surface="hard", best_of=3, now=CUTOFF + timedelta(hours=4),
        cutoff=CUTOFF,
    )


def test_aces_can_project_with_canonical_depth_and_no_provider_calls():
    replay = [match(i) for i in range(1, 16)]
    state = build_market_state(replay, {"atp:a", "atp:b"}, CUTOFF)
    assert state["provider_requests"] == 0
    assert state["canonical_stat_matches"] == 15
    value = project(state)
    assert value["aces"]["player1"]["samples"] == 15
    assert value["aces"]["player2"]["samples"] == 15
    assert value["aces"]["player1"]["estimate"] > value["aces"]["player2"]["estimate"]
    assert value["aces"]["total_estimate"] > 0
    assert value["double_faults"]["player1"]["samples"] == 15
    assert value["aces"]["not_betting_odds"] is True
    reversed_value = project(state, left="atp:b", right="atp:a")
    assert reversed_value["aces"]["player1"] == value["aces"]["player2"]
    assert reversed_value["aces"]["total_estimate"] == value["aces"]["total_estimate"]


def test_same_day_and_unfinished_events_cannot_leak():
    base = [match(i) for i in range(1, 12)]
    before = build_market_state(base, {"atp:a", "atp:b"}, CUTOFF)
    future = match(0, aces_a=1000, aces_b=1000)
    pending = match(12, aces_a=1000, aces_b=1000, status="retired")
    after = build_market_state(base + [future, pending], {"atp:a", "atp:b"}, CUTOFF)
    assert project(before) == project(after)
    assert after["canonical_stat_matches"] == 11


def test_fewer_than_six_samples_stay_unavailable_not_imputed():
    state = build_market_state([match(i) for i in range(1, 6)], {"atp:a", "atp:b"}, CUTOFF)
    assert project(state)["aces"]["player1"] is None
    assert project(state)["aces"]["total_estimate"] is None


def test_identity_is_tour_scoped_and_unknown_is_not_fabricated():
    rows = [match(i) for i in range(1, 12)] + [match(i, "wta", aces_a=20) for i in range(1, 12)]
    state = build_market_state(rows, {"atp:a", "atp:b", "wta:a", "wta:b"}, CUTOFF)
    assert project(state, tour="atp")["aces"]["player1"]["estimate"] < 10
    assert project(state, left="wta:a", right="wta:b", tour="wta")["aces"]["player1"]["estimate"] > 10
    assert project(state, left="atp:unknown")["aces"] is None


def test_missing_and_nonfinite_market_stats_do_not_create_evidence():
    missing = [match(i, aces_a=None, aces_b=float("nan")) for i in range(1, 15)]
    state = build_market_state(missing, {"atp:a", "atp:b"}, CUTOFF)
    assert project(state)["aces"] is None
    assert project(state)["double_faults"]["player1"] is not None


def test_cutoff_mismatch_and_tampered_sample_fail_closed():
    state = build_market_state([match(i) for i in range(1, 10)], {"atp:a", "atp:b"}, CUTOFF)
    assert project_market_state(
        state, left_key="atp:a", right_key="atp:b", tour="atp",
        surface="hard", best_of=3, now=CUTOFF + timedelta(hours=1),
        cutoff=CUTOFF + timedelta(days=1)
    )["aces"] is None
    state["players"]["atp:a"]["samples"][0]["scheduled_at"] = CUTOFF.isoformat()
    assert project(state)["aces"] is None
