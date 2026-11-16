"""Safety regressions for the opt-in ATP 2016-2018 native source linker."""
from link_atpworldtour_stats import (
    STAT_COLUMNS,
    _player_stats,
    _reciprocal_stats_valid,
)

# Native ATP World Tour 2020 source record from the pinned 2022 archive schema.
EXAMPLE = (
    "2020-451-ms001-7-1-re44-mw02,doha,"
    "/en/scores/match-stats/archive/2020/451/ms001,01:27:00,87,"
    "re44,289,3,0,44,58,34,44,6,14,1,2,10,176,22,48,7,14,3,6,"
    "10,40,58,29,62,69,120,mw02,248,0,3,48,62,26,48,7,14,3,6,"
    "10,140,10,44,8,14,1,2,10,33,62,18,58,51,120"
)


def record():
    values = EXAMPLE.split(",")
    assert len(values) == len(STAT_COLUMNS) == 59
    return dict(zip(STAT_COLUMNS, values))


def test_strict_reciprocal_point_and_bp_conservation_accepts_real_row():
    assert _reciprocal_stats_valid(record())


def test_strict_reciprocal_rejects_one_sided_bp_and_return_mismatch():
    row = record()
    row["loser_break_points_saved"] = "2"
    assert not _reciprocal_stats_valid(row)
    row = record()
    row["winner_return_points_won"] = "28"
    assert not _reciprocal_stats_valid(row)


def test_default_import_mapping_remains_unchanged():
    assert "break_point_return_win" not in _player_stats("winner", record())
    assert "break_point_serve_win" not in _player_stats("winner", record())


def test_optin_native_break_point_rates_for_both_sides():
    row = record()
    winner = _player_stats("winner", row, include_break_points=True)
    loser = _player_stats("loser", row, include_break_points=True)
    assert winner["break_point_serve_win"] == 0.5
    assert winner["break_point_return_win"] == 0.5
    assert loser["break_point_serve_win"] == 0.5
    assert loser["break_point_return_win"] == 0.5


def test_no_bp_opportunities_are_missing_not_zero_percent():
    row = record()
    row["winner_break_points_saved"] = "0"
    row["winner_break_points_serve_total"] = "0"
    stats = _player_stats("winner", row, include_break_points=True)
    assert "break_point_serve_win" not in stats
    assert stats["break_point_return_win"] == 0.5


def test_bad_bp_denominator_never_generates_an_invalid_rate():
    row = record()
    row["winner_break_points_saved"] = "7"
    row["winner_break_points_serve_total"] = "2"
    stats = _player_stats("winner", row, include_break_points=True)
    assert "break_point_serve_win" not in stats
