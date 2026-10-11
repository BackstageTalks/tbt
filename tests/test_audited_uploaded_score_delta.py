"""Isolated add-only score writer guards for prior complete matches."""
import json
import sys
import hashlib
from pathlib import Path
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from import_audited_uploaded_score_delta import (
    FIELDS, FLAGS, YEARS, patch_year, verified_stage, digest
)

def synthetic():
    old=json.dumps({"total_sets":2},separators=(",",":"))
    df=pd.DataFrame([
        {"match_id":"old1","tour":"atp",
         "scheduled_at":pd.Timestamp("2022-06-18T12:00:00Z"),
         "player1_id":"one","player2_id":"two","winner_id":"one",
         "stats_json":old},
        {"match_id":"old2","tour":"atp",
         "scheduled_at":pd.Timestamp("2022-07-19T12:00:00Z"),
         "player1_id":"three","player2_id":"four","winner_id":"four",
         "stats_json":json.dumps({"total_games":20})}
    ])
    r={"canonical_match_id":"old1","canonical_year_sha256":"a"*64,
       "canonical_existing_stats_sha256":hashlib.sha256(old.encode()).hexdigest(),
       "match_player1_id":"one","match_player2_id":"two","match_winner_id":"one",
       "source_record_date":"2022-06-18",
       "add_only_missing_score_fields":{"total_games":24,"deciding_set":0}}
    return df,r

def test_actual_missing_null_only_preserve_other_complete_rows():
    df,r=synthetic()
    after,summary=patch_year(df,[r],2022,"a"*64)
    assert summary["changed_matches"]==1
    assert summary["added_values"]==2
    assert summary["existing_values_overwritten"]==0
    assert json.loads(after.iloc[0].stats_json)=={"total_sets":2,"total_games":24,"deciding_set":0}
    assert after.iloc[1].stats_json==df.iloc[1].stats_json
    assert df.iloc[0].stats_json=='{"total_sets":2}'

def test_no_overwrite_even_when_value_equal():
    df,r=synthetic()
    r["add_only_missing_score_fields"]["total_sets"]=2
    with pytest.raises(ValueError,match="overwritten"):
        patch_year(df,[r],2022,"a"*64)

def test_mismatch_identity_and_old_stat_hash_refused():
    df,r=synthetic()
    for k,v in (("match_player1_id","wrong"),("match_winner_id","four"),
                ("source_record_date","2022-06-19"),
                ("canonical_year_sha256","b"*64),
                ("canonical_existing_stats_sha256","b"*64)):
        candidate=dict(r);candidate[k]=v
        with pytest.raises(ValueError):
            patch_year(df,[candidate],2022,"a"*64)

def test_existing_other_columns_unchanged_and_null_replay_fails():
    df,r=synthetic()
    after,_=patch_year(df,[r],2022,"a"*64)
    with pytest.raises(ValueError):
        patch_year(after,[r],2022,"a"*64)

def test_strict_typed_numeric_domain_keys():
    assert "p1_first_set_won" in FLAGS
    assert "total_games" in FIELDS
    assert "player1_rank" not in FIELDS
    assert YEARS==(2020,2021,2022,2023,2024,2025)

def test_sha256_pinned_original_stage(monkeypatch,tmp_path):
    import import_audited_uploaded_score_delta as imp
    import gzip
    df,r=synthetic()
    row={"schema":1,"policy":"READ_ONLY_CANDIDATE_NOT_WRITER_APPROVED_POSTMATCH_ONLY",
         "canonical_match_id":"old1","canonical_year":2022,
         "canonical_year_sha256":"a"*64,
         "canonical_existing_stats_sha256":r["canonical_existing_stats_sha256"],
         "source_sha256":"c"*64,"source_observation_sha256":"d"*64,
         "source_link":{"orientation":"direct"},
         "source_record_date":"2022-06-18","match_player1_id":"one",
         "match_player2_id":"two","match_winner_id":"one",
         "add_only_missing_score_fields":{"total_games":24}}
    archive=tmp_path/"scores.jsonl.gz"
    with gzip.open(archive,"wt") as f:
        f.write(json.dumps(row)+"\n")
    report=tmp_path/"report.json"
    report.write_text(json.dumps({
      "schema":1,"candidate_stage_rows":1,
      "completed_match_score_comparison":{"stageable_score_missing_cells_read_only":1},
      "canonical":{"year_partitions":78},"safety":{"no_cdb_writes":True}}))
    monkeypatch.setattr(imp,"STAGE_SHA",digest(archive))
    monkeypatch.setattr(imp,"REPORT_SHA",digest(report))
    monkeypatch.setattr(imp,"SCORE_ROWS",1)
    monkeypatch.setattr(imp,"SCORE_CELLS",1)
    items,summary=verified_stage(archive,report)
    assert len(items)==1 and summary[2022]==1
    row["add_only_missing_score_fields"]["player1_rank"]=1
    with gzip.open(archive,"wt") as f: f.write(json.dumps(row)+"\n")
    monkeypatch.setattr(imp,"STAGE_SHA",digest(archive))
    with pytest.raises(ValueError,match="Invalid source identity"):
        verified_stage(archive,report)
