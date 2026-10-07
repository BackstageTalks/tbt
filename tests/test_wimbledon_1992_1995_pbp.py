from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

import link_wimbledon_1992_1995_pbp as mod


def _match(*, p1="Jim Courier", p2="Markus Zoecke", r1=1, r2=59, winner=1):
    return SimpleNamespace(
        match_id="m1",
        tour="atp",
        scheduled_at=datetime(1992, 6, 22, 12, 0, tzinfo=timezone.utc),
        player1_id="p1",
        player1_name=p1,
        player2_id="p2",
        player2_name=p2,
        player1_rank=r1,
        player2_rank=r2,
        round_name="R128",
        winner_id="p1" if winner == 1 else "p2",
        surface="grass",
        tournament="Wimbledon",
    )


def _rows():
    i = pd.Series({
        "player":"I","name":"J.Courier","name_opp":"M.Zoecke","year":1992,"round":1,
        "rank":1,"rank_opp":59,"winnerofm":1,
        "T":3,"T2":1,"Tin1":2,"Tin2":1,"Twinin1":1,"Twinin2":1,
        "Twin":2,"Tace":1,"Tdf":0,
    })
    j = pd.Series({
        "player":"J","name":"M.Zoecke","name_opp":"J.Courier","year":1992,"round":1,
        "rank":59,"rank_opp":1,"winnerofm":0,
        "T":2,"T2":1,"Tin1":1,"Tin2":0,"Twinin1":1,"Twinin2":0,
        "Twin":1,"Tace":0,"Tdf":1,
    })
    return {"I": i, "J": j}


def _points():
    return pd.DataFrame([
        {"mid":"x","pinm":1,"sinm":1,"gins":1,"ping":1,"server":1,"win":1,"in1":1,"in2":None,"winin1":1,"winin2":None,"ace":1,"df":0,"breakp":0},
        {"mid":"x","pinm":2,"sinm":1,"gins":1,"ping":2,"server":1,"win":0,"in1":1,"in2":None,"winin1":0,"winin2":None,"ace":0,"df":0,"breakp":1},
        {"mid":"x","pinm":3,"sinm":1,"gins":1,"ping":3,"server":1,"win":1,"in1":0,"in2":1,"winin1":None,"winin2":1,"ace":0,"df":0,"breakp":1},
        {"mid":"x","pinm":4,"sinm":1,"gins":2,"ping":1,"server":2,"win":1,"in1":1,"in2":None,"winin1":1,"winin2":None,"ace":0,"df":0,"breakp":0},
        {"mid":"x","pinm":5,"sinm":1,"gins":2,"ping":2,"server":2,"win":0,"in1":0,"in2":0,"winin1":None,"winin2":0,"ace":0,"df":1,"breakp":1},
    ])


def test_initial_surname_key_is_exact_not_fuzzy():
    assert mod.initial_surname_key("J.Courier") == "j courier"
    assert mod.initial_surname_key("Jim Courier") == "j courier"
    assert mod.initial_surname_key("John Courier") == "j courier"
    assert mod.initial_surname_key("Courier") == ""


def test_source_point_totals_reconcile_exactly():
    ok, issues = mod._point_internal_validation(_rows(), _points())
    assert ok is True
    assert issues == []

    bad = _rows()
    bad["I"]["Tace"] = 2
    ok, issues = mod._point_internal_validation(bad, _points())
    assert ok is False
    assert any("Tace" in issue for issue in issues)


def test_resolve_requires_winner_and_round_or_ranks():
    rows = _rows()
    match, orientation, scored = mod._resolve_source_match(rows, [_match()])
    assert match is not None
    assert orientation == "direct"
    assert scored[0]["score"] >= 5

    wrong_winner = _match(winner=2)
    match, orientation, _ = mod._resolve_source_match(rows, [wrong_winner])
    assert match is None
    assert orientation is None

    wrong_rank = _match(r1=2)
    match, orientation, _ = mod._resolve_source_match(rows, [wrong_rank])
    assert match is None


def test_incoming_stats_and_break_point_rates():
    incoming, detail = mod._incoming_stats(_rows(), _points(), "direct")
    assert incoming["p1_aces"] == 1
    assert incoming["p2_double_faults"] == 1
    assert incoming["p1_first_serve_win"] == 0.5
    assert incoming["p1_second_serve_win"] == 1.0
    assert incoming["p1_service_points_won"] == 2 / 3
    assert incoming["p1_return_points_won"] == 0.5
    # Courier faced two break points and won one of them.
    assert incoming["p1_break_point_serve_win"] == 0.5
    # Zoecke faced one break point and lost it, so Courier return BP win = 1.
    assert incoming["p1_break_point_return_win"] == 1.0
    assert detail["source_I"]["service_points"] == 3
