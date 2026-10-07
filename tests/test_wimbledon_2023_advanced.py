from __future__ import annotations

from datetime import datetime,timezone
from types import SimpleNamespace

import pandas as pd

import link_wimbledon_2023_advanced as mod


def _frame():
    return pd.DataFrame([
        {
            "match_id":"s1","player1":"Ons Jabeur","player2":"Elena Rybakina",
            "elapsed_time":"00:00:00","set_no":1,"game_no":1,"point_no":1,
            "p1_sets":0,"p2_sets":0,"p1_games":0,"p2_games":0,"p1_score":0,"p2_score":15,
            "server":2,"serve_no":1,"point_victor":2,"p1_points_won":0,"p2_points_won":1,
            "game_victor":0,"set_victor":0,"p1_ace":0,"p2_ace":1,"p1_winner":0,"p2_winner":1,
            "winner_shot_type":"F","p1_double_fault":0,"p2_double_fault":0,
            "p1_unf_err":0,"p2_unf_err":0,"p1_net_pt":0,"p2_net_pt":0,
            "p1_net_pt_won":0,"p2_net_pt_won":0,"p1_break_pt":0,"p2_break_pt":0,
            "p1_break_pt_won":0,"p2_break_pt_won":0,"p1_break_pt_missed":0,"p2_break_pt_missed":0,
            "p1_distance_run":1.0,"p2_distance_run":1.2,"rally_count":1,"speed_mph":110,
            "ServeWidth":"W","ServeDepth":"CTL","ReturnDepth":None,
        },
        {
            "match_id":"s1","player1":"Ons Jabeur","player2":"Elena Rybakina",
            "elapsed_time":"00:01:00","set_no":1,"game_no":1,"point_no":2,
            "p1_sets":0,"p2_sets":0,"p1_games":0,"p2_games":0,"p1_score":15,"p2_score":15,
            "server":2,"serve_no":2,"point_victor":1,"p1_points_won":1,"p2_points_won":1,
            "game_victor":0,"set_victor":1,"p1_ace":0,"p2_ace":0,"p1_winner":1,"p2_winner":0,
            "winner_shot_type":"B","p1_double_fault":0,"p2_double_fault":0,
            "p1_unf_err":0,"p2_unf_err":0,"p1_net_pt":0,"p2_net_pt":1,
            "p1_net_pt_won":0,"p2_net_pt_won":0,"p1_break_pt":1,"p2_break_pt":0,
            "p1_break_pt_won":1,"p2_break_pt_won":0,"p1_break_pt_missed":0,"p2_break_pt_missed":0,
            "p1_distance_run":8.0,"p2_distance_run":10.0,"rally_count":5,"speed_mph":92,
            "ServeWidth":"BC","ServeDepth":"NCTL","ReturnDepth":"D",
        },
        {
            "match_id":"s1","player1":"Ons Jabeur","player2":"Elena Rybakina",
            "elapsed_time":"00:02:00","set_no":2,"game_no":1,"point_no":3,
            "p1_sets":1,"p2_sets":0,"p1_games":0,"p2_games":0,"p1_score":0,"p2_score":15,
            "server":1,"serve_no":1,"point_victor":2,"p1_points_won":1,"p2_points_won":2,
            "game_victor":0,"set_victor":2,"p1_ace":0,"p2_ace":0,"p1_winner":0,"p2_winner":1,
            "winner_shot_type":"F","p1_double_fault":0,"p2_double_fault":0,
            "p1_unf_err":1,"p2_unf_err":0,"p1_net_pt":0,"p2_net_pt":0,
            "p1_net_pt_won":0,"p2_net_pt_won":0,"p1_break_pt":0,"p2_break_pt":1,
            "p1_break_pt_won":0,"p2_break_pt_won":1,"p1_break_pt_missed":0,"p2_break_pt_missed":0,
            "p1_distance_run":5.0,"p2_distance_run":4.0,"rally_count":3,"speed_mph":100,
            "ServeWidth":"C","ServeDepth":"CTL","ReturnDepth":"ND",
        },
        {
            "match_id":"s1","player1":"Ons Jabeur","player2":"Elena Rybakina",
            "elapsed_time":"00:03:00","set_no":3,"game_no":1,"point_no":4,
            "p1_sets":1,"p2_sets":1,"p1_games":0,"p2_games":0,"p1_score":0,"p2_score":15,
            "server":1,"serve_no":2,"point_victor":2,"p1_points_won":1,"p2_points_won":3,
            "game_victor":2,"set_victor":2,"p1_ace":0,"p2_ace":0,"p1_winner":0,"p2_winner":0,
            "winner_shot_type":0,"p1_double_fault":1,"p2_double_fault":0,
            "p1_unf_err":0,"p2_unf_err":0,"p1_net_pt":0,"p2_net_pt":0,
            "p1_net_pt_won":0,"p2_net_pt_won":0,"p1_break_pt":0,"p2_break_pt":1,
            "p1_break_pt_won":0,"p2_break_pt_won":1,"p1_break_pt_missed":0,"p2_break_pt_missed":0,
            "p1_distance_run":0.0,"p2_distance_run":0.0,"rally_count":0,"speed_mph":78,
            "ServeWidth":"W","ServeDepth":"NCTL","ReturnDepth":None,
        },
    ])


def _match():
    return SimpleNamespace(
        match_id="m1",tour="wta",scheduled_at=datetime(2023,7,12,12,0,tzinfo=timezone.utc),
        tournament="Wimbledon",round_name="QF",
        player1_id="p1",player1_name="Ons Jabeur",
        player2_id="p2",player2_name="Elena Rybakina",
        winner_id="p2",
    )


def test_integrity_and_winner():
    frame=_frame()
    assert mod._validate_group(frame)==[]
    assert mod._winner_from_sets(frame)==2
    bad=frame.copy()
    bad.loc[1,"p1_points_won"]=0
    assert "cumulative_points_do_not_equal_point_no" in mod._validate_group(bad)


def test_aggregate_advanced_fields():
    frame=_frame()
    p1=mod._aggregate(frame,1)
    p2=mod._aggregate(frame,2)
    assert p1["service_points"]==2
    assert p1["double_faults"]==1
    assert p2["aces"]==1
    assert p1["break_points"]==1
    assert p1["break_points_won"]==1
    assert p2["break_points"]==2
    assert p2["serve_speed_mph_max"]==110


def test_orientation_and_canonical_winner():
    frame=_frame()
    match=_match()
    assert mod._source_to_canonical_orientation(frame,match)=="direct"
    assert mod._canonical_winner_side(match)==2
