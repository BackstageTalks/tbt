from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts.link_pointbypoint_serve_return import (
    _parse_pbp,
    _source_files,
    _source_tour,
    _winner_side,
    _historical_alias_indexes,
    _resolve_historical_alias,
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


def _match(mid, name1, name2, pid1="player-1", pid2="player-2", day="2016-05-05"):
    return SimpleNamespace(
        match_id=mid, tour="atp", scheduled_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
        player1_id=pid1, player2_id=pid2, player1_name=name1, player2_name=name2,
        tournament="Madrid", round_name="R16", surface="Clay", winner_id=pid1,
    )


def test_unique_canonical_historical_alias_requires_same_canonical_id():
    history = [
        _match("prior", "JoaoSousa", "Jack Sock", day="2015-05-05"),
        _match("target", "Joao Sousa", "Jack Sock"),
    ]
    result = _resolve_historical_alias(
        _historical_alias_indexes(history),
        "atp", "2016-05-05", "JoaoSousa", "Jack Sock",
        "Madrid", "Clay", "R16",
    )
    assert result is not None
    assert result[0].match_id == "target"
    assert result[1] == ((1, "p1"), (2, "p2"))
    assert result[2] == "canonical_historical_alias"


def test_compact_name_requires_unique_global_id_and_event_corroboration():
    indexes = _historical_alias_indexes([_match("target", "Joao Sousa", "Jack Sock")])
    matched = _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Madrid", "Clay", "R16",
    )
    assert matched is not None
    assert matched[2] == "canonical_unique_compact_alias"
    assert _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Other", "Clay", "R16",
    ) is None
    assert _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Madrid", "Hard", "R16",
    ) is None
    assert _resolve_historical_alias(
        indexes, "atp", "2016-05-06", "JoaoSousa", "Jack Sock", "Madrid", "Clay", "R16",
    ) is None


def test_homonym_canonical_ids_never_become_alias_matches():
    matches = [
        _match("target", "Joao Sousa", "Jack Sock"),
        _match("homonym", "JoaoSousa", "Different Person", pid1="other-id", pid2="different-id", day="2017-05-05"),
    ]
    assert _resolve_historical_alias(
        _historical_alias_indexes(matches),
        "atp", "2016-05-05", "JoaoSousa", "Jack Sock", "Madrid", "Clay", "R16",
    ) is None


def test_source_orientation_can_be_swapped_without_guessing_identity():
    indexes = _historical_alias_indexes([_match("target", "Joao Sousa", "Jack Sock")])
    matched = _resolve_historical_alias(
        indexes, "atp", "2016-05-05", "Jack Sock", "JoaoSousa", "Madrid", "Clay", "R16",
    )
    assert matched is not None
    assert matched[1] == ((1, "p2"), (2, "p1"))
