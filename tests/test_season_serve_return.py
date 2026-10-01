from __future__ import annotations

from pathlib import Path

from scripts.link_season_serve_return import _parse_row, _percent


def _row(**overrides):
    row = {
        "match_id": "69894353",
        "season_year": "2026",
        "tour_type": "1",
        "tour_type_human": "ATP Tour",
        "date_timestamp": "1767320100",
        "date_human": "02 Jan 2026",
        "tournament": "United Cup ATP",
        "round": "",
        "surface": "hard",
        "status": "FINISHED",
        "status_extra": "FINISHED",
        "home_name": "Munar J.",
        "away_name": "Baez S.",
        "home_id": "292653",
        "away_id": "956292",
        "winner_code": "2",
        "home_aces": "7",
        "away_aces": "0",
        "home_double_faults": "0",
        "away_double_faults": "2",
        "home_service_points_won_perc": "60",
        "away_service_points_won_perc": "59",
        "home_return_points_won_perc": "41",
        "away_return_points_won_perc": "40",
    }
    row.update(overrides)
    return row


def test_percent_parses_whole_percent_source_values():
    assert _percent("61") == 0.61
    assert _percent("0") == 0.0
    assert _percent("100") == 1.0
    assert _percent("") is None
    assert _percent("101") is None


def test_parse_finished_row_validates_complement_and_counts():
    parsed, reason = _parse_row(
        _row(),
        path=Path("2026-atp-season.csv"),
        source_sha256="abc",
    )
    assert reason == "ok"
    assert parsed is not None
    assert parsed.tour == "atp"
    assert parsed.winner_name == "Baez S."
    assert parsed.home_stats["service_points_won"] == 0.60
    assert parsed.home_stats["return_points_won"] == 0.41
    assert parsed.home_stats["aces"] == 7.0
    assert parsed.away_stats["double_faults"] == 2.0


def test_parse_rejects_retired_walkover_and_canceled_rows():
    for status_extra in ("RETIRED", "WALKOVER", "CANCELED"):
        parsed, reason = _parse_row(
            _row(status_extra=status_extra),
            path=Path("2026-atp-season.csv"),
            source_sha256="abc",
        )
        assert parsed is None
        assert reason == "non_standard_finish"


def test_parse_rejects_bad_quality_semantics():
    parsed, reason = _parse_row(
        _row(
            home_service_points_won_perc="0",
            away_service_points_won_perc="0",
            home_return_points_won_perc="0",
            away_return_points_won_perc="0",
        ),
        path=Path("2026-atp-season.csv"),
        source_sha256="abc",
    )
    assert parsed is None
    assert reason == "inconsistent_quality_rates"


def test_parse_wta_tour_and_source_identity():
    parsed, reason = _parse_row(
        _row(tour_type="2", tour_type_human="WTA Tour"),
        path=Path("2026-wta-season.csv"),
        source_sha256="abc",
    )
    assert reason == "ok"
    assert parsed is not None
    assert parsed.tour == "wta"
    assert parsed.source_id == "season:wta:69894353"
