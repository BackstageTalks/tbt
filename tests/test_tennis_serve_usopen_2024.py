from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

import link_tennis_serve_usopen_2024 as mod


def _match(mid, p1, p2, round_name="R128"):
    return SimpleNamespace(
        match_id=mid,
        scheduled_at=datetime(2024, 8, 26, 15, 0, tzinfo=timezone.utc),
        tournament="US Open",
        round_name=round_name,
        player1_name=p1,
        player2_name=p2,
        player1_id=f"{mid}-1",
        player2_id=f"{mid}-2",
        tour="atp",
    )


def test_link_unique_pair_and_aggregate(monkeypatch):
    frame = pd.DataFrame([
        {
            "match_id":"src1","server":"Novak Djokovic","player1":"Novak Djokovic","player2":"Radu Albot",
            "Speed_KMH":190,"SetNo":1,"GameNo":1,"PointNumber":1,"ServeNumber":1,"ServeResult":"Ace",
            "round":"First Round","ElapsedTime":"00:01:10",
        },
        {
            "match_id":"src1","server":"Radu Albot","player1":"Novak Djokovic","player2":"Radu Albot",
            "Speed_KMH":170,"SetNo":1,"GameNo":2,"PointNumber":2,"ServeNumber":2,"ServeResult":"In",
            "round":"First Round","ElapsedTime":"00:03:10",
        },
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
    assert rows[0]["player2_serve"]["second_serve_speed_kmh_mean"] == 170
    assert rows[0]["feature_policy"].startswith("research_post_match_only")


def test_ambiguous_pair_is_rejected(monkeypatch):
    frame = pd.DataFrame([{
        "match_id":"src1","server":"A","player1":"A","player2":"B",
        "Speed_KMH":180,"SetNo":1,"GameNo":1,"PointNumber":1,"ServeNumber":1,"ServeResult":"In",
        "round":"","ElapsedTime":"00:01:00",
    }])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda matches: (matches, {"quarantined_rows":0}),
    )
    rows, report = mod.link(frame, [_match("m1","A","B"), _match("m2","A","B")])
    assert rows == []
    assert report["counts"]["ambiguous"] == 1
