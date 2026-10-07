from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

import link_tennis_serve_usopen_2024 as mod


def _match(mid, p1, p2, round_name="R128", tour="atp"):
    return SimpleNamespace(
        match_id=mid,
        scheduled_at=datetime(2024, 8, 26, 15, 0, tzinfo=timezone.utc),
        tournament="US Open",
        round_name=round_name,
        player1_name=p1,
        player2_name=p2,
        player1_id=f"{mid}-1",
        player2_id=f"{mid}-2",
        tour=tour,
    )


def _row(match_id, server, returner, *, gender="M", speed=180, serve_number=1, ace=0):
    return {
        "filename":f"{match_id}.npy",
        "match_id":match_id,
        "server":server,
        "returner":returner,
        "gender":gender,
        "height_cm":188,
        "point_number":1,
        "point_winner":1,
        "serve_number":serve_number,
        "speed_kmh":speed,
        "serve_width":"W",
        "serve_depth":"CTL",
        "return_depth":"D",
        "n_frames":80,
        "duration_sec":1.33,
        "quality_label":2.0,
        "ace":ace,
        "rally_count":3,
        "set_no":1,
        "game_no":1,
    }


def test_link_real_schema_unique_pair_and_aggregate(monkeypatch):
    frame = pd.DataFrame([
        _row("src1","Novak Djokovic","Radu Albot",speed=190,serve_number=1,ace=1),
        _row("src1","Radu Albot","Novak Djokovic",speed=170,serve_number=2,ace=0),
    ])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda matches: (matches, {"quarantined_rows":0}),
    )
    rows, report = mod.link(frame, [_match("m1","Novak Djokovic","Radu Albot")])
    assert len(rows) == 1
    assert report["counts"]["linked_matches"] == 1
    assert rows[0]["player1_serve"]["speed_kmh_mean"] == 190
    assert rows[0]["player1_serve"]["ace_count"] == 1
    assert rows[0]["player2_serve"]["second_serve_speed_kmh_mean"] == 170
    assert rows[0]["feature_policy"].startswith("research_post_match_only")


def test_ambiguous_pair_is_rejected(monkeypatch):
    frame = pd.DataFrame([
        _row("src1","A","B"),
        _row("src1","B","A"),
    ])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda matches: (matches, {"quarantined_rows":0}),
    )
    rows, report = mod.link(frame, [_match("m1","A","B"), _match("m2","A","B")])
    assert rows == []
    assert report["counts"]["ambiguous"] == 1


def test_gender_filters_tour(monkeypatch):
    frame = pd.DataFrame([
        _row("src1","A","B",gender="F"),
        _row("src1","B","A",gender="F"),
    ])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda matches: (matches, {"quarantined_rows":0}),
    )
    rows, report = mod.link(
        frame,
        [_match("m1","A","B",tour="atp"), _match("m2","A","B",tour="wta")],
    )
    assert len(rows) == 1
    assert rows[0]["match_id"] == "m2"
    assert report["counts"]["linked_matches"] == 1


def test_incomplete_real_schema_fails_closed(monkeypatch):
    frame = pd.DataFrame([{"match_id":"x","server":"A","returner":"B"}])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda matches: (matches, {"quarantined_rows":0}),
    )
    try:
        mod.link(frame, [])
    except ValueError as exc:
        assert "Missing serve metadata columns" in str(exc)
    else:
        raise AssertionError("expected missing-schema failure")
