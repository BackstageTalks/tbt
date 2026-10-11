"""Regression for pinned Wimbledon 2023 count/rate collision (morning refresh)."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from tbt.data.history_snapshot import (
    _interpret_wimbledon_2023_count_fields,
    _validate_stats,
    load_snapshot,
    write_snapshot,
)


def test_pinned_count_values_do_not_feed_rate_inputs(match_factory, tmp_path):
    match = replace(
        match_factory("wimbledon-pilot", "a", "b", "a"),
        tour="wta",
        scheduled_at=datetime(2023, 7, 12, 11, tzinfo=timezone.utc),
        tournament="Wimbledon",
        player1_name="Ons Jabeur",
        player2_name="Elena Rybakina",
        stats={
            "p1_break_points_won": 0,
            "p2_break_points_won": 4,
            "p1_break_points": 9,
            "p1_aces": 7,
        },
    )
    destination = tmp_path / "history-2023.parquet"
    write_snapshot([match], destination)
    restored = load_snapshot(destination)[0]
    assert "p1_break_points_won" not in restored.stats
    assert "p2_break_points_won" not in restored.stats
    assert restored.stats["p1_break_points_won_count"] == 0
    assert restored.stats["p2_break_points_won_count"] == 4
    assert restored.stats["p1_break_points"] == 9
    assert restored.stats["p1_aces"] == 7
    # The release remains byte-for-byte unchanged by the reader.
    assert match.stats["p2_break_points_won"] == 4


@pytest.mark.parametrize("name1,name2", [
    ("Ons Jabeur", "Aryna Sabalenka"),
    ("Marketa Vondroušová", "Elina Svitolina"),
])
def test_pinned_orientation_and_diacritics(name1, name2):
    result = _interpret_wimbledon_2023_count_fields(
        {"p1_break_points_won": 1, "p2_break_points_won": 5},
        tour="wta", scheduled_at=datetime(2023, 7, 13, tzinfo=timezone.utc),
        tournament="Wimbledon", player1_name=name1, player2_name=name2,
    )
    assert _validate_stats(result)["p2_break_points_won_count"] == 5
    assert "p1_break_points_won" not in result


def test_other_matches_still_fail_closed_on_out_of_range_rate():
    kwargs = dict(tour="wta", scheduled_at=datetime(2024, 7, 13, tzinfo=timezone.utc),
        tournament="Wimbledon", player1_name="Ons Jabeur", player2_name="Elena Rybakina")
    with pytest.raises(ValueError, match="Rate statistic out of range"):
        _validate_stats(_interpret_wimbledon_2023_count_fields(
            {"p2_break_points_won": 4}, **kwargs
        ))


@pytest.mark.parametrize("bad", [-1, 201, 0.5, float("nan"), True])
def test_pinned_bad_counts_fail_closed(bad):
    with pytest.raises(ValueError, match="Invalid pinned Wimbledon count"):
        _interpret_wimbledon_2023_count_fields(
            {"p2_break_points_won": bad}, tour="wta",
            scheduled_at=datetime(2023, 7, 12, tzinfo=timezone.utc),
            tournament="Wimbledon", player1_name="Ons Jabeur",
            player2_name="Elena Rybakina",
        )



@pytest.mark.parametrize("player1,player2,date", [
    ("Ons Jabeur", "Elena Rybakina", "2023-07-12T12:00:00Z"),
    ("Madison Keys", "Aryna Sabalenka", "2023-07-12T12:30:00Z"),
    ("Ons Jabeur", "Aryna Sabalenka", "2023-07-13T12:30:00Z"),
    ("Elina Svitolina", "Marketa Vondrousova", "2023-07-13T14:15:00Z"),
    ("Marketa Vondrousova", "Ons Jabeur", "2023-07-15T13:00:00Z"),
])
def test_repair_raw_wimbledon_2023_count_rows_match_canonical_reader(
    player1, player2, date
):
    import json
    from scripts.repair_history_data import invalid_reason

    row = {
        "match_id": "wimbledon-fixture",
        "player1_id": "101",
        "player2_id": "202",
        "player1_name": player1,
        "player2_name": player2,
        "tour": "wta",
        "tournament": "Wimbledon",
        "scheduled_at": date,
        "stats_json": json.dumps({
            "p1_break_points_won": 4,
            "p2_break_points_won": 0,
            "p1_aces": 8,
        }),
    }
    assert invalid_reason(row) is None


@pytest.mark.parametrize("changes", [
    {"tour": "atp"},
    {"tournament": "Not Wimbledon"},
    {"scheduled_at": "2024-07-12T12:00:00Z"},
    {"player2_name": "Unrelated Player"},
])
def test_repair_still_quarantines_other_out_of_range_rate_rows(changes):
    import json
    from scripts.repair_history_data import invalid_reason

    row = {
        "match_id": "not-pinned",
        "player1_id": "101", "player2_id": "202",
        "player1_name": "Ons Jabeur", "player2_name": "Elena Rybakina",
        "tour": "wta", "tournament": "Wimbledon",
        "scheduled_at": "2023-07-12T12:00:00Z",
        "stats_json": json.dumps({"p2_break_points_won": 4}),
        **changes,
    }
    assert invalid_reason(row) == "invalid_statistics"


@pytest.mark.parametrize("bad", [-1, 0.5, 201, True])
def test_repair_rejects_invalid_pinned_count_even_for_known_match(bad):
    import json
    from scripts.repair_history_data import invalid_reason

    row = {
        "match_id": "pinned-bad-count",
        "player1_id": "101", "player2_id": "202",
        "player1_name": "Ons Jabeur", "player2_name": "Elena Rybakina",
        "tour": "wta", "tournament": "Wimbledon",
        "scheduled_at": "2023-07-12T12:00:00Z",
        "stats_json": json.dumps({"p2_break_points_won": bad}),
    }
    assert invalid_reason(row) == "invalid_statistics"
