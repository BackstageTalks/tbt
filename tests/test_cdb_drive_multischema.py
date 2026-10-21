"""Observed Drive match schemas: fail-closed normalization and rate provenance."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.cdb_inbox_adapter import normalize
from scripts.cdb_inbox_adapter import run as normalize_batch
from scripts.link_offline_serve_return import _paired_percent, _service_stats, _return_rate


def count_source(**changes):
    row = {
        "tour": "ATP", "tourney_date": "20261001",
        "tourney_name": "Vienna", "winner_name": "Alpha One",
        "loser_name": "Beta Two", "surface": "hard", "round": "QF",
        "start_time_utc": "2026-10-17T19:05:00Z",
        "w_svpt": "70", "w_1stIn": "40", "w_1stWon": "30",
        "w_2ndWon": "14", "l_svpt": "60", "l_1stIn": "35",
        "l_1stWon": "25", "l_2ndWon": "11",
    }
    row.update(changes)
    return row


def season_source(**changes):
    timestamp = int(datetime(2026, 10, 17, 12, tzinfo=timezone.utc).timestamp())
    row = {
        "match_id": "provider-only-42", "tour_type_human": "ATP Tour",
        "date_timestamp": str(timestamp), "date_human": "17 Oct 2026",
        "tournament": "Vienna ATP", "round": "QF", "surface": "hard",
        "status": "FINISHED", "status_extra": "FINISHED",
        "home_name": "Alpha One", "away_name": "Beta Two",
        "home_id": "untrusted-11", "away_id": "untrusted-22",
        "winner_code": "2", "home_set_score": "0", "away_set_score": "2",
        "home_aces": "3", "away_aces": "4",
        "home_double_faults": "2", "away_double_faults": "1",
        "home_service_points_won_perc": "43",
        "away_return_points_won_perc": "57",
        "away_service_points_won_perc": "75",
        "home_return_points_won_perc": "25",
        "home_break_points_saved_perc": "71",
        "away_break_points_won_perc": "29",
        "away_break_points_saved_perc": "50",
        "home_break_points_won_perc": "50",
    }
    row.update(changes)
    return row


def test_match_start_overrides_tourney_date_without_identity_shortcuts():
    from scripts.cdb_inbox_adapter import normalize as parse
    good, why = parse(count_source(), "atp_matches_2026.csv", 1)
    assert why == ""
    assert good["tourney_date"] == "20261017"
    assert good["winner_name"] == "Alpha One"
    for changed, reason in (
        ({"start_time_utc": "2026-10-18T00:05:00Z"},
         "match_date_tournament_window_conflict"),
        ({"start_time_utc": "2026-09-30T23:00:00Z"},
         "match_date_tournament_window_conflict"),
        ({"start_time_utc": "2026-10-17T19:05:00"},
         "match_start_invalid"),
        ({"match_date": "2026-10-16"}, "conflicting_match_dates"),
    ):
        row, why = parse(count_source(**changed), "atp_matches_2026.csv", 1)
        assert row is None and why == reason


def test_season_home_away_orientation_and_complementary_rates(tmp_path):
    from scripts.cdb_inbox_adapter import normalize as parse
    source = season_source()
    row, why = parse(source, "2026-atp-season.csv", 1)
    assert why == ""
    assert (row["league"], row["tourney_name"], row["winner_name"],
            row["loser_name"]) == ("atp", "Vienna", "Beta Two", "Alpha One")
    assert row["w_ace"] == "4" and row["l_ace"] == "3"
    assert row["source_winner_id"] == "untrusted-22"
    assert "winner_id" not in row
    assert row["w_service_points_won_pct"] == "75"
    assert row["l_return_points_won_pct"] == "25"
    assert row["w_break_points_won_pct"] == "29"
    assert row["l_break_points_saved_pct"] == "71"
    assert row["w_svpt"] == ""
    assert _service_stats("w", row)["service_points_won"] == pytest.approx(0.75)
    assert _return_rate("l", row) == pytest.approx(0.25)

    input_folder = tmp_path / "input"
    input_folder.mkdir()
    with (input_folder / "2026-atp-season.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(source))
        w.writeheader()
        w.writerow(source)
    report = normalize_batch(input_folder, tmp_path / "out")
    assert report["counts"]["normalized_rows"] == 1
    assert report["state"] == "SOURCE_ONLY"
    assert report["production_mutated"] is False
    assert report["api_requests"] == 0


def test_invalid_percentage_pair_cannot_write_fake_rates():
    from scripts.cdb_inbox_adapter import normalize as parse
    row, why = parse(season_source(home_service_points_won_perc="0",
                                   away_return_points_won_perc="0"),
                     "2026-atp-season.csv", 1)
    assert why == ""
    assert row["l_service_points_won_pct"] == ""
    assert row["w_return_points_won_pct"] == ""
    assert "service_points_won" not in _service_stats("l", row)
    for a, b in (("0", "0"), ("101", "-1"), ("99", "99"),
                 ("nan", "100"), ("", "50")):
        assert _paired_percent({"w_service_points_won_pct": a,
                                "l_return_points_won_pct": b},
                               "w_service_points_won_pct",
                               "l_return_points_won_pct") is None


def test_season_rejects_nonfinished_ambiguous_winners_and_unverified_tour():
    from scripts.cdb_inbox_adapter import normalize as parse
    for changes, reason in (
        ({"tour_type_human": "Challenger"}, "tour_missing_or_unsupported"),
        ({"status": "CANCELLED"}, "match_not_finished"),
        ({"winner_code": "0"}, "winner_unverified"),
        ({"home_set_score": "2", "away_set_score": "0"},
         "season_score_winner_conflict"),
        ({"date_timestamp": "unknown"}, "date_missing_or_invalid"),
        ({"date_human": "13 Oct 2026"}, "conflicting_match_dates"),
        ({"home_name": "Beta Two", "away_name": "Beta Two"},
         "players_missing_or_equal"),
    ):
        row, why = parse(season_source(**changes), "2026-atp-season.csv", 1)
        assert row is None and why == reason

