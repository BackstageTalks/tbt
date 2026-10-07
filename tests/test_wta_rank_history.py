from datetime import datetime
from types import SimpleNamespace
import csv
import pytest

from tbt.data.wta_rank_history import WTARankHistory, WTA_RANK_HISTORY_FEATURE_NAMES
from tbt.services.training import PRODUCTION_FEATURE_NAMES, _candidate_feature_names


def test_wta_rank_history_is_strictly_point_in_time():
    rows=[
        {"date":datetime(2024,12,2).date(),"name":"Alpha One","rank":40,"points":800},
        {"date":datetime(2024,12,2).date(),"name":"Beta Two","rank":20,"points":1200},
        {"date":datetime(2024,12,30).date(),"name":"Alpha One","rank":30,"points":1000},
        {"date":datetime(2024,12,30).date(),"name":"Beta Two","rank":10,"points":1800},
        {"date":datetime(2025,1,6).date(),"name":"Alpha One","rank":1,"points":4000},
        {"date":datetime(2025,1,6).date(),"name":"Beta Two","rank":2,"points":3500},
    ]
    history=WTARankHistory(rows)
    match=SimpleNamespace(
        tour="wta",
        scheduled_at=datetime.fromisoformat("2025-01-06T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )
    f=history.features_for_match(match)
    assert f["wta_hist_known_both"]==1.0
    import math
    expected=math.log1p(10)-math.log1p(30)
    assert abs(f["wta_hist_rank_advantage"]-expected)<1e-12


def test_sackmann_player_id_join_and_candidate_governance(tmp_path):
    players=tmp_path/"players.csv"
    players.write_text("player_id,name_first,name_last,hand,birth_date,country_code\n1,Alpha,One,R,20000101,USA\n2,Beta,Two,L,20000101,CZE\n")
    ranks=tmp_path/"ranks.csv"
    ranks.write_text("ranking_date,ranking,player_id,ranking_points,tours\n20241230,30,1,1000,0\n20241230,10,2,1800,0\n")
    history=WTARankHistory.from_sackmann(players,[ranks])
    match=SimpleNamespace(
        tour="wta",
        scheduled_at=datetime.fromisoformat("2025-01-02T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )
    assert history.features_for_match(match)["wta_hist_known_both"]==1.0
    assert not (set(WTA_RANK_HISTORY_FEATURE_NAMES)&set(PRODUCTION_FEATURE_NAMES))
    assert not (set(WTA_RANK_HISTORY_FEATURE_NAMES)&set(_candidate_feature_names()))
    assert set(WTA_RANK_HISTORY_FEATURE_NAMES).issubset(
        _candidate_feature_names(wta_rank_history=history)
    )



def _write_wta_players(path):
    path.write_text(
        "player_id,name_first,name_last,hand,birth_date,country_code\n"
        "1,Alpha,One,R,20000101,USA\n"
        "2,Beta,Two,L,20000101,CZE\n"
    )


def test_current_file_cannot_rewrite_pinned_historical_decade(tmp_path):
    players = tmp_path / "wta_players.csv"
    _write_wta_players(players)
    historical = tmp_path / "wta_rankings_00s.csv"
    historical.write_text(
        "ranking_date,ranking,player_id,ranking_points,tours\n"
        "20040510,30,1,1000,0\n"
        "20040510,10,2,1800,0\n"
    )
    current = tmp_path / "wta_rankings_current.csv"
    current.write_text(
        "ranking_date,ranking,player_id,ranking_points,tours\n"
        # Same pinned historical date, intentionally conflicting correction.
        "20040510,25,1,1200,0\n"
        "20040510,11,2,1700,0\n"
        # Extension beyond historical max remains eligible.
        "20040517,24,1,1250,0\n"
        "20040517,9,2,1900,0\n"
    )
    history = WTARankHistory.from_sackmann(players, [historical, current])

    old_match = SimpleNamespace(
        tour="wta",
        scheduled_at=datetime.fromisoformat("2004-05-11T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )
    old = history.features_for_match(old_match)
    import math
    assert old["wta_hist_known_both"] == 1.0
    assert old["wta_hist_rank_advantage"] == pytest.approx(
        math.log1p(10) - math.log1p(30)
    )

    new_match = SimpleNamespace(
        tour="wta",
        scheduled_at=datetime.fromisoformat("2004-05-18T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )
    new = history.features_for_match(new_match)
    assert new["wta_hist_rank_advantage"] == pytest.approx(
        math.log1p(9) - math.log1p(24)
    )


def test_conflicting_historical_wta_files_quarantine_ambiguous_key(tmp_path):
    players = tmp_path / "wta_players.csv"
    _write_wta_players(players)
    first = tmp_path / "wta_rankings_00s.csv"
    second = tmp_path / "wta_rankings_00s_part2.csv"
    first.write_text(
        "ranking_date,ranking,player_id,ranking_points,tours\n"
        "20040510,30,1,1000,0\n"
        "20040510,10,2,1800,0\n"
    )
    second.write_text(
        "ranking_date,ranking,player_id,ranking_points,tours\n"
        "20040510,25,1,1200,0\n"
    )
    history = WTARankHistory.from_sackmann(players, [first, second])
    match = SimpleNamespace(
        tour="wta",
        scheduled_at=datetime.fromisoformat("2004-05-11T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )
    features = history.features_for_match(match)
    assert features["wta_hist_known_both"] == 0.0


def test_current_only_wta_source_remains_valid(tmp_path):
    players = tmp_path / "wta_players.csv"
    _write_wta_players(players)
    current = tmp_path / "wta_rankings_current.csv"
    current.write_text(
        "ranking_date,ranking,player_id,ranking_points,tours\n"
        "20260928,30,1,1000,0\n"
        "20260928,10,2,1800,0\n"
    )
    history = WTARankHistory.from_sackmann(players, [current])
    match = SimpleNamespace(
        tour="wta",
        scheduled_at=datetime.fromisoformat("2026-09-29T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )
    assert history.features_for_match(match)["wta_hist_known_both"] == 1.0
