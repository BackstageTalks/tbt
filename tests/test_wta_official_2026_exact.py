"""Regression contracts for additive, exact-cell WTA PIT rank patch and readback."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from scripts.import_wta_official_2026_exact import _patch


def fixture():
    return pd.DataFrame([{
        "match_id": "wta-123", "tour": "wta",
        "scheduled_at": pd.Timestamp("2026-07-14T12:00:00Z"),
        "player1_id": "canonical-1", "player2_id": "canonical-2",
        "player1_name": "Jane Doe", "player2_name": "Lucy Example",
        "player1_rank": float("nan"), "player2_rank": float("nan"),
        "stats_json": '{"p1_aces":3}', "other_immutable_col": "KEEP_UNCHANGED",
        "provider_context_json": '{"venue":"Centre Court"}',
    }, {
        "match_id": "wta-other", "tour": "wta",
        "scheduled_at": pd.Timestamp("2026-07-15T12:00:00Z"),
        "player1_id": "canonical-3", "player2_id": "canonical-4",
        "player1_name": "Other One", "player2_name": "Other Two",
        "player1_rank": 95., "player2_rank": 188.,
        "stats_json": '{"p1_aces":5}', "other_immutable_col": "PRESERVE",
        "provider_context_json": '{"venue":"Outdoor"}',
    }])


def proposal():
    return {"schema":1, "candidate_only":True, "tour":"wta", "match_id":"wta-123",
            "scheduled_at":"2026-07-14T12:00:00+00:00",
            "player1_id":"canonical-1", "player2_id":"canonical-2",
            "player1_name":"Jane Doe","player2_name":"Lucy Example",
            "sackmann_player1_id":"100001","sackmann_player2_id":"100002",
            "ranking_as_of":"2026-07-13","canonical":[None,None],
            "proposed":[12,38]}


def test_exact_additive_rank_cells_and_pit_provenance_only():
    before=fixture()
    after,counts=_patch(before,[proposal()])
    assert counts["updated"]==1 and counts["rank_fields_added"]==2
    assert counts["existing_rank_values_overwritten"]==0
    assert pd.isna(before.at[0,"player1_rank"])
    assert int(after.at[0,"player1_rank"])==12
    assert int(after.at[0,"player2_rank"])==38
    provenance=json.loads(after.at[0,"provider_context_json"])["_tbt_rank_provenance"]
    assert provenance["point_in_time"] is True
    assert provenance["as_of"]=="2026-07-13T00:00:00+00:00"
    assert after.at[0,"other_immutable_col"]=="KEEP_UNCHANGED"
    assert after.at[0,"stats_json"]=='{"p1_aces":3}'
    pd.testing.assert_frame_equal(before.iloc[1:],after.iloc[1:])


@pytest.mark.parametrize("key,value",[
    ("player1_id","other-user"),
    ("scheduled_at","2026-07-15T12:00:00Z"),
    ("ranking_as_of","2026-07-14"),
    ("ranking_as_of","2026-07-04"),
    ("canonical",[7,None]),
    ("proposed",[0,38]),
    ("candidate_only",False),
    ("sackmann_player1_id","not-an-id"),
    ("tour","atp"),
])
def test_reject_unverified_stage(key,value):
    r=proposal();r[key]=value
    with pytest.raises((ValueError,TypeError)):
        _patch(fixture(),[r])


def test_reject_existing_rank_conflict():
    before=fixture()
    before.at[0,"player1_rank"]=13.
    with pytest.raises(ValueError):
        _patch(before,[proposal()])


def test_preserve_one_existing_matching_rank_and_context():
    before=fixture()
    before.at[0,"player1_rank"]=12.
    old_context={"_tbt_rank_provenance":{"point_in_time":True,"source":"prior_snapshot",
                                              "as_of":"2026-07-12T00:00:00+00:00"}}
    before.at[0,"provider_context_json"]=json.dumps(old_context)
    stage=proposal();stage["canonical"]=[12,None]
    after,report=_patch(before,[stage])
    assert report["rank_fields_added"]==1
    assert after.at[0,"player1_rank"]==12
    assert after.at[0,"provider_context_json"]==before.at[0,"provider_context_json"]


def test_never_mutate_duplicate_canonical_id():
    before=fixture()
    before.at[1,"match_id"]="wta-123"
    with pytest.raises(ValueError):
        _patch(before,[proposal()])


def test_never_mutate_duplicate_stage():
    with pytest.raises(ValueError):
        from scripts.import_wta_official_2026_exact import _read_stage
        # Verified duplicates are checked by the input reader in production.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"stage.jsonl"
            path.write_text((json.dumps(proposal())+"\n")*2)
            _read_stage(path)
