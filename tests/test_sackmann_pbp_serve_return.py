from __future__ import annotations

from scripts.link_sackmann_pbp_serve_return import _date, _parse_pbp, _tour


def test_parse_regular_games_and_set_boundary():
    parsed, error = _parse_pbp("SSSS;RRRR.SSSS;RRRR")
    assert error == ""
    assert parsed is not None
    assert parsed[0]["service_points"] == 8
    assert parsed[0]["service_points_won"] == 1.0
    assert parsed[0]["return_points"] == 8
    assert parsed[0]["return_points_won"] == 1.0
    assert parsed[1]["service_points"] == 8
    assert parsed[1]["service_points_won"] == 0.0
    assert parsed[1]["return_points_won"] == 0.0


def test_parse_ace_double_fault_semantics():
    parsed, error = _parse_pbp("AAAD;SSSR")
    assert error == ""
    assert parsed is not None
    assert parsed[0]["service_points"] == 4
    assert parsed[0]["service_points_won"] == 0.75
    assert parsed[1]["service_points"] == 4
    assert parsed[1]["service_points_won"] == 0.75


def test_parse_tiebreak_service_changes():
    parsed, error = _parse_pbp("SS/RR/SS/RR")
    assert error == ""
    assert parsed is not None
    assert parsed[0]["service_points"] > 0
    assert parsed[1]["service_points"] > 0
    assert parsed[0]["return_points"] > 0
    assert parsed[1]["return_points"] > 0


def test_parse_rejects_unknown_symbols():
    parsed, error = _parse_pbp("SSXRRRR")
    assert parsed is None
    assert error.startswith("unsupported_pbp_char:")


def test_tour_and_date_normalization():
    assert _tour("ATP") == "atp"
    assert _tour("CH") == "atp"
    assert _tour("FU") == "atp"
    assert _tour("WTA") == "wta"
    assert _tour("ITF") == "wta"
    assert _date("25 Oct 10").isoformat() == "2010-10-25"
