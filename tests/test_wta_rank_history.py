from datetime import datetime
from types import SimpleNamespace
import csv

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
