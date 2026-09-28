from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tbt.models.feature_builder import FEATURE_STATE_SCHEMA_VERSION, FeatureBuilder
from tbt.schemas import MatchRecord


def _match(match_id: str, when: datetime, *, stats=None, winner="p1"):
    return MatchRecord(
        match_id=match_id,
        tour="atp",
        scheduled_at=when,
        player1_id="p1",
        player1_name="Player One",
        player2_id="p2",
        player2_name="Player Two",
        surface="hard",
        tournament="Test Event",
        tournament_id="t1",
        tournament_level="A",
        round_name="R32",
        winner_id=winner,
        status="completed",
        best_of=3,
        stats=stats or {},
        provider_payload={},
    )


def _rich_stats():
    return {
        "p1_first_strike_serve_win": 0.60,
        "p2_first_strike_serve_win": 0.40,
        "p1_return_in_play_rate": 0.90,
        "p2_return_in_play_rate": 0.80,
        "p1_return_deep_rate": 0.65,
        "p2_return_deep_rate": 0.50,
        "p1_break_point_serve_win": 0.70,
        "p2_break_point_serve_win": 0.55,
        "p1_break_point_return_win": 0.45,
        "p2_break_point_return_win": 0.30,
        "p1_net_points_win": 0.75,
        "p2_net_points_win": 0.55,
        "p1_attacking_points_rate": 0.55,
        "p2_attacking_points_rate": 0.35,
        "p1_unforced_error_rate": 0.20,
        "p2_unforced_error_rate": 0.30,
    }


def test_rich_charting_rates_become_prior_only_rolling_features():
    start = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    builder = FeatureBuilder()
    first = _match("m1", start, stats=_rich_stats())
    future = _match("m2", start + timedelta(days=2))

    before = builder.snapshot(first)
    assert before["rich_charting_known_both"] == 0.0
    assert before["first_strike_serve_diff"] == 0.0

    builder.update(first)
    after = builder.snapshot(future)
    assert after["rich_charting_known_both"] == pytest.approx(1.0)
    assert after["first_strike_serve_diff"] == pytest.approx(0.20)
    assert after["return_in_play_diff"] == pytest.approx(0.10)
    assert after["return_depth_diff"] == pytest.approx(0.15)
    assert after["break_point_serve_diff"] == pytest.approx(0.15)
    assert after["break_point_return_diff"] == pytest.approx(0.15)
    assert after["net_efficiency_diff"] == pytest.approx(0.20)
    # aggression balance = attacking rate - unforced error rate
    assert after["aggression_balance_diff"] == pytest.approx(0.30)


def test_same_utc_day_rich_charting_does_not_leak_between_matches():
    day = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    first = _match("m1", day, stats=_rich_stats())
    second = _match("m2", day + timedelta(hours=4), stats=_rich_stats(), winner="p2")
    frame = FeatureBuilder().build_training_frame([first, second])

    assert len(frame) == 2
    assert frame["rich_charting_known_both"].tolist() == [0.0, 0.0]
    assert frame["first_strike_serve_diff"].tolist() == [0.0, 0.0]


def test_rich_charting_feature_state_round_trip_and_v2_compatibility():
    start = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    builder = FeatureBuilder()
    builder.update(_match("m1", start, stats=_rich_stats()))

    payload = builder.export_state()
    assert payload["schema_version"] == FEATURE_STATE_SCHEMA_VERSION == 3
    restored = FeatureBuilder.from_state(payload)
    snapshot = restored.snapshot(_match("m2", start + timedelta(days=2)))
    assert snapshot["rich_charting_known_both"] == pytest.approx(1.0)
    assert snapshot["net_efficiency_diff"] == pytest.approx(0.20)

    legacy = builder.export_state()
    legacy["schema_version"] = 2
    for player in legacy["players"].values():
        for item in player["recent"]:
            for field in (
                "first_strike_serve", "return_in_play", "return_depth",
                "break_point_serve", "break_point_return", "net_efficiency",
                "aggression_balance",
            ):
                item.pop(field, None)
    legacy_builder = FeatureBuilder.from_state(legacy)
    legacy_snapshot = legacy_builder.snapshot(_match("m3", start + timedelta(days=3)))
    assert legacy_snapshot["rich_charting_known_both"] == 0.0
