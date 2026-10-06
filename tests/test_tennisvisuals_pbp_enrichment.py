from pathlib import Path

from scripts.link_pointbypoint_serve_return import (
    _parse_pbp,
    _source_files,
    _source_tour,
    _winner_side,
)


def test_tennisvisuals_zero_based_winner_mapping():
    assert _winner_side("0", zero_based=True) == 1
    assert _winner_side("1", zero_based=True) == 2
    assert _winner_side("2", zero_based=True) is None
    assert _winner_side("1") == 1
    assert _winner_side("2") == 2


def test_tennisvisuals_tour_mapping_for_lower_tours():
    assert _source_tour({"tour": "ATP"}, Path("ATP_Singles_pbp.csv")) == "atp"
    assert _source_tour({"tour": "CHALLENGER"}, Path("CHALLENGER_Singles_pbp.csv")) == "atp"
    assert _source_tour({"tour": "ITF Men"}, Path("ITF-Men_Singles_pbpx.csv")) == "atp"
    assert _source_tour({"tour": "WTA"}, Path("WTA_Singles_pbpx.csv")) == "wta"
    assert _source_tour({"tour": "WTA 125K"}, Path("WTA-125K_Singles_pbpx.csv")) == "wta"
    assert _source_tour({"tour": "ITF Women"}, Path("ITF-Women_Singles_pbpx.csv")) == "wta"


def test_source_files_accepts_validated_singles_and_rejects_doubles(tmp_path):
    names = [
        "pbp_matches_atp_main_archive.csv",
        "ATP_Singles_pbp.csv",
        "ATP_Singles_pbpx.csv",
        "ITF-Men_Singles_pbpx.csv",
        "WTA_Doubles_pbpx.csv",
    ]
    for name in names:
        (tmp_path / name).write_text("date,server1,server2,pbp\n", encoding="utf-8")
    selected = {p.name for p in _source_files(tmp_path)}
    assert "pbp_matches_atp_main_archive.csv" in selected
    assert "ATP_Singles_pbp.csv" in selected
    assert "ATP_Singles_pbpx.csv" in selected
    assert "ITF-Men_Singles_pbpx.csv" in selected
    assert "WTA_Doubles_pbpx.csv" not in selected


def test_validated_rich_pbp_parser_handles_lowercase_aces_and_double_faults():
    parsed = _parse_pbp("sAsrS;SDsSrS;SsRSRRsDSrSRSS")
    assert parsed is not None
    assert parsed["point_count"] > 0
    assert 0.0 <= parsed[1]["service_points_won"] <= 1.0
    assert 0.0 <= parsed[2]["return_points_won"] <= 1.0
