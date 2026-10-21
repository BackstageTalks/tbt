"""Fail-closed source paths for bounded original Sackmann 7z archives."""
import pytest
from scripts.cdb_native_7z_unpack import source_path

@pytest.mark.parametrize("entry,expected", [
    ("atp/atp_matches_2025.csv", ("atp", "atp_matches_2025.csv")),
    ("atp/atp_matches_futures_2026.csv", ("atp", "atp_matches_futures_2026.csv")),
    ("wta/wta_matches_qual_itf_2024.csv", ("wta", "wta_matches_qual_itf_2024.csv")),
    ("slam_pointbypoint/2024-usopen-points.csv",
     ("slam_pointbypoint", "2024-usopen-points.csv")),
    ("slam_pointbypoint/2024-usopen-matches.csv",
     ("slam_pointbypoint", "2024-usopen-matches.csv")),
    ("atp/UPSTREAM_README.md", ("atp", "UPSTREAM_README.md")),
])
def test_exact_native_allowlist(entry, expected):
    assert source_path(entry, 2016, 2026) == expected


@pytest.mark.parametrize("entry", [
    "/atp/atp_matches_2025.csv",
    "atp/../atp_matches_2025.csv",
    "atp\\atp_matches_2025.csv",
    "wta/wta_matches_futures_2025.csv",
    "atp/wta_matches_2025.csv",
    "slam_pointbypoint/atp_matches_2025.csv",
    "atp/atp_matches_2025.csv/extra",
    "evil/atp_matches_2025.csv",
])
def test_unsafe_or_wrong_namespaces_fail_closed(entry):
    with pytest.raises(ValueError):
        source_path(entry, 2016, 2026)


def test_out_of_year_scope_is_never_extracted():
    assert source_path("atp/atp_matches_2015.csv", 2016, 2026) is None
    assert source_path("slam_pointbypoint/2011-usopen-points.csv", 2016, 2026) is None


def test_ignores_unrelated_player_rank_files():
    assert source_path("atp/atp_players.csv", 2016, 2026) is None
    assert source_path("wta/wta_rankings_current.csv", 2016, 2026) is None
