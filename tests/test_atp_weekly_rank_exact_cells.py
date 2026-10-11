"""Exact ATP historic rank null-only writer synthetic contract."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from import_atp_weekly_rank_exact_cells import apply, bounded_rank, absent


def fixtures():
    cols=["match_id","tour","scheduled_at","player1_id","player1_name",
          "player2_id","player2_name","player1_rank","player2_rank",
          "provider_context_json","stats_json"]
    base={year:pd.DataFrame(columns=cols) for year in (2024,2025,2026)}
    base[2024]=pd.DataFrame([{
        "match_id":"atp-match","tour":"atp",
        "scheduled_at":pd.Timestamp("2024-05-07T12:00:00Z"),
        "player1_id":"111","player1_name":"Alice Test",
        "player2_id":"222","player2_name":"Bob Test",
        "player1_rank":None,"player2_rank":None,
        "provider_context_json":json.dumps({"existing":"preserve"}),
        "stats_json":'{"p1_aces":4}',
    }])
    candidate={
        "schema":1,"source":"atp_rankings_ishanjha_weekly","match_id":"atp-match",
        "scheduled_at":"2024-05-07T12:00:00+00:00",
        "player1_id":"111","player1_name":"Alice Test",
        "player2_id":"222","player2_name":"Bob Test",
        "existing_player1_rank":None,"existing_player2_rank":None,
        "incoming_player1_rank":23,"incoming_player2_rank":31,
        "source_week":"2024-05-06",
    }
    return base,candidate


def test_adds_two_only_missing_week_before_match():
    before,candidate=fixtures()
    out,c=apply(before,[candidate],expected_matches=1,expected_fields=2,expected_stale=0)
    assert c["player1_rank_filled"]==c["player2_rank_filled"]==1
    assert out[2024].loc[0,"player1_rank"]==23
    assert out[2024].loc[0,"player2_rank"]==31
    assert out[2024].loc[0,"stats_json"]==before[2024].loc[0,"stats_json"]
    new=json.loads(out[2024].loc[0,"provider_context_json"])
    assert new["existing"]=="preserve"
    assert new["_tbt_rank_provenance"]["as_of"]=="2024-05-06T00:00:00+00:00"


def test_nonnull_collision_rejected():
    before,candidate=fixtures()
    before[2024].at[0,"player1_rank"]=24
    candidate["existing_player1_rank"]=24
    with pytest.raises(ValueError,match="Forbidden rank collision"):
        apply(before,[candidate],expected_matches=1,expected_fields=1,expected_stale=0)


def test_source_identity_drift_rejected():
    before,candidate=fixtures()
    before[2024].at[0,"player1_id"]="other"
    with pytest.raises(ValueError,match="identity"):
        apply(before,[candidate],expected_matches=1,expected_fields=2,expected_stale=0)


def test_rank_time_window_and_source_boundary():
    before,candidate=fixtures()
    candidate["source_week"]="2024-05-07"
    with pytest.raises(ValueError,match="Unexpected source/CDB delta"):
        apply(before,[candidate],expected_matches=1,expected_fields=2,expected_stale=0)
    out,c=apply(before,[candidate],expected_matches=0,expected_fields=0,expected_stale=1)
    assert c["changed_matches"]==0
    assert absent(out[2024].at[0,"player1_rank"])
    candidate["source_week"]="2024-04-22"
    _,c=apply(before,[candidate],expected_matches=0,expected_fields=0,expected_stale=1)
    assert c["stale_or_same_day_excluded"]==1


def test_existing_provider_provenance_collision_rejected():
    before,candidate=fixtures()
    before[2024].at[0,"provider_context_json"]=json.dumps({
        "_tbt_rank_provenance":{"source":"different","as_of":"2024-05-06T00:00:00+00:00"}})
    with pytest.raises(ValueError,match="provenance conflict"):
        apply(before,[candidate],expected_matches=1,expected_fields=2,expected_stale=0)


def test_rank_numeric_input_constraints():
    for bad in (0,-1,30001,"12x","3.5","NaN",True):
        with pytest.raises(ValueError):
            bounded_rank(bad)
    assert bounded_rank("243")==243
