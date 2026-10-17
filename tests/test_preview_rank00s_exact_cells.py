"""Offline-only synthetic safety contracts for isolated ATP rank00s exact-cell preview."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import preview_rank00s_exact_cells as m


def fixture():
    rows=pd.DataFrame([
        {"match_id":"a","tour":"atp","scheduled_at":"2003-03-11T12:00:00Z",
         "player1_id":"one","player2_id":"two","player1_rank":None,
         "player2_rank":None,"stats_json":'{"aces":1}',"tournament_id":"t1"},
        {"match_id":"b","tour":"atp","scheduled_at":"2003-03-11T12:00:00Z",
         "player1_id":"three","player2_id":"four","player1_rank":10,
         "player2_rank":20,"stats_json":'{"aces":2}',"tournament_id":"t2"},
    ])
    row={"canonical_year":2003,"match_id":"a","field":"player1_rank",
         "canonical_player1_id":"one","canonical_player2_id":"two",
         "candidate_value":1334,"source_date":"2003-03-10"}
    return {2003:rows},row


def test_exact_two_null_cells_and_all_untouched_values():
    frames,row=fixture()
    patched,count=m.preview(frames,[row,dict(row,field="player2_rank",candidate_value=250)])
    assert count["candidate_cells"]==2
    assert patched[2003].loc[0,"player1_rank"]==1334
    assert patched[2003].loc[0,"player2_rank"]==250
    pd.testing.assert_series_equal(patched[2003].iloc[1],frames[2003].iloc[1])
    assert patched[2003].loc[0,"stats_json"]==frames[2003].loc[0,"stats_json"]
    assert pd.isna(frames[2003].loc[0,"player1_rank"])


def test_existing_nonnull_never_overwritten():
    frames,row=fixture()
    frames[2003].at[0,"player1_rank"]=37
    with pytest.raises(m.Blocked,match="No NULL CAS"):
        m.preview(frames,[row])


def test_swapped_canonical_players_rejected():
    frames,row=fixture()
    with pytest.raises(m.Blocked,match="orientation"):
        m.preview(frames,[dict(row,canonical_player1_id="two",canonical_player2_id="one")])


def test_missing_or_duplicate_canonical_match_rejected():
    frames,row=fixture()
    with pytest.raises(m.Blocked,match="absent"):
        m.preview(frames,[dict(row,match_id="missing")])
    with pytest.raises(m.Blocked,match="duplicated"):
        m.preview(frames,[row,row])
    frames[2003].at[1,"match_id"]="a"
    with pytest.raises(m.Blocked,match="Duplicate"):
        m.preview(frames,[row])


@pytest.mark.parametrize("bad",["2003-03-11","2003-03-12","2003-02-24"])
def test_same_day_future_or_stale_rank_rejected(bad):
    frames,row=fixture()
    with pytest.raises(m.Blocked,match="snapshot"):
        m.preview(frames,[dict(row,source_date=bad)])


def test_naive_or_wrong_tour_and_year_rejected():
    frames,row=fixture()
    frames[2003].at[0,"scheduled_at"]="2003-03-11T12:00:00"
    with pytest.raises(m.Blocked,match="Naive"):
        m.preview(frames,[row])
    frames,row=fixture()
    frames[2003].at[0,"tour"]="wta"
    with pytest.raises(m.Blocked,match="tour/year"):
        m.preview(frames,[row])
    frames[2003].at[0,"tour"]="atp"
    frames[2003].at[0,"scheduled_at"]="2004-03-11T12:00:00Z"
    with pytest.raises(m.Blocked,match="tour/year"):
        m.preview(frames,[row])


def test_missing_canonical_columns_rejected():
    frames,row=fixture()
    with pytest.raises(m.Blocked,match="schema"):
        m.preview({2003:frames[2003].drop(columns=["player1_rank"])},[row])


def sample_stage(**updates):
    row={"canonical_year":2003,"match_id":"a","field":"player1_rank",
         "canonical_player1_id":"one","canonical_player2_id":"two",
         "candidate_value":1334,"source_date":"2003-03-10",
         "canonical_partition_sha256":m.PARTITIONS[2003][0],
         "source_csv_sha256":m.SOURCE_CSV_SHA,
         "source_baseline_history_manifest_sha256":m.MANIFEST_SHA,
         "source_player_id":"101","status":"REVIEW_ONLY_NO_WRITE",
         "expected_current_value":None,"tour":"atp"}
    row.update(updates)
    return row


def save(tmp_path,row,overrides=None):
    p=tmp_path/"candidate.jsonl"
    p.write_text(json.dumps(row)+"\n",encoding="utf8")
    report={"state":"PREPARED_READONLY_NO_CDB_WRITE",
            "safe_for_production_write":False,"canonical_writes":0,
            "history_manifest_sha256":m.MANIFEST_SHA,
            "source_counts":{"rows":920907,"missing_points":516},
            "candidate_cells":1,"stage_sha256":m.sha256(p)}
    report.update(overrides or {})
    r=tmp_path/"preflight_report.json"
    r.write_text(json.dumps(report),encoding="utf8")
    return r,p


def test_bounded_pinned_readonly_stage_accepted_but_never_write_authorized(tmp_path):
    report,stage=save(tmp_path,sample_stage())
    assert len(m.stage(report,stage))==1
    payload=json.loads(report.read_text())
    payload["safe_for_production_write"]=True
    report.write_text(json.dumps(payload))
    with pytest.raises(m.Blocked,match="unsafe"):
        m.stage(report,stage)


@pytest.mark.parametrize("bad",[0,-1,30001,True,"1334"])
def test_invalid_rank_blocked(tmp_path,bad):
    report,stage=save(tmp_path,sample_stage(candidate_value=bad))
    with pytest.raises(m.Blocked,match="ranking"):
        m.stage(report,stage)


@pytest.mark.parametrize("updates",[
    {"canonical_player2_id":"one"},
    {"source_player_id":"104711"},
    {"source_csv_sha256":"x"*64},
    {"expected_current_value":37},
    {"field":"stats_json"},
    {"tour":"wta"},
])
def test_stage_namespace_pin_field_or_cas_drift_rejected(tmp_path,updates):
    report,stage=save(tmp_path,sample_stage(**updates))
    with pytest.raises(m.Blocked):
        m.stage(report,stage)


def test_stage_digest_tamper_and_zero_candidates_blocked(tmp_path):
    report,stage=save(tmp_path,sample_stage())
    stage.write_text(stage.read_text()+"\n#tampered")
    with pytest.raises(m.Blocked,match="stale"):
        m.stage(report,stage)


def test_canonical_output_location_cannot_be_targeted(tmp_path):
    root=tmp_path/"CDB"
    root.mkdir()
    for out in (root,root/"child",tmp_path):
        with pytest.raises(m.Blocked,match="isolated"):
            m.run(root,tmp_path/"no_report",tmp_path/"no_stage",out)
