"""Regression tests for native converted break-point count import."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import csv
import pytest
from tbt.schemas import MatchRecord
from import_historical_match_foundation import _stats
from recover_cdb_sackmann_breakpoints import source_match_id
from import_cdb_sackmann_bp_counts import stage,write_local
from audit_cdb_sackmann_bp_count_gap import candidate,source_bp_counts
from offline_exact_cdb_write import _additions

def source():
    return {"tourney_id":"2020-101","tourney_date":"20200106",
            "match_num":"42","round":"F","winner_id":"1001","loser_id":"1002",
            "winner_name":"Alpha One","loser_name":"Beta Two",
            "score":"6-4 6-4","best_of":"3",
            "w_svpt":"64","w_SvGms":"10","w_1stIn":"40","w_1stWon":"30",
            "w_2ndWon":"14","w_bpSaved":"3","w_bpFaced":"5",
            "w_ace":"5","w_df":"2","l_svpt":"65","l_SvGms":"10",
            "l_1stIn":"41","l_1stWon":"25","l_2ndWon":"12",
            "l_bpSaved":"2","l_bpFaced":"7","l_ace":"4","l_df":"3"}

def match(row):
    path=Path("atp_matches_2020.csv")
    mid,kind=source_match_id("atp",path,row,2)
    return MatchRecord(
        match_id=mid,tour="atp",
        scheduled_at=datetime(2020,1,6,12,tzinfo=timezone.utc),
        player1_id="hist-js:atp:1001",player2_id="hist-js:atp:1002",
        player1_name="Alpha One",player2_name="Beta Two",
        winner_id="hist-js:atp:1001",status="completed",
        stats=_stats(row),provider_payload={
            "_tbt_provider_event_id":mid,
            "_tbt_source_category_name":"historical_"+kind,
            "_tbt_statistics":{"source":"jeff_sackmann_match_snapshot:"+path.name}
        })

def fixture(root,rows):
    path=root/"atp"/"atp_matches_2020.csv"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="") as out:
        writer=csv.DictWriter(out,fieldnames=list(source()))
        writer.writeheader()
        writer.writerows(rows)
    return path

def test_values_are_integer_counts_with_zero_not_missing():
    row=source()
    assert source_bp_counts(row)=={
        "p1_return_break_points_converted_count":5,
        "p2_return_break_points_converted_count":2}
    row["l_bpFaced"]="0";row["l_bpSaved"]="0"
    assert source_bp_counts(row)["p1_return_break_points_converted_count"]==0

def test_exact_source_matching_and_zero_overwrite(tmp_path):
    row=source()
    path=fixture(tmp_path,[row])
    m=match(row)
    # Both the source hash and historical metadata must match natively.
    native_kind=source_match_id("atp",path,row,2)[1]
    additions,why=candidate(m,row,"atp",native_kind,path)
    assert why=="eligible"
    shard=int(m.match_id.rsplit(":",1)[-1][:8],16)%256
    rows,counts=stage([m],tmp_path,modulus=256,index=shard)
    assert counts["staged_matches"]==1
    assert counts["new_stat_values"]==2
    before=deepcopy(m)
    assert write_local([m],rows,tmp_path,modulus=256,index=shard)==[2020]
    assert m.stats["p1_return_break_points_converted_count"]==5
    assert m.stats["p2_return_break_points_converted_count"]==2
    assert all(m.stats[k]==v for k,v in before.stats.items())
    rows2,counts2=stage([m],tmp_path,modulus=256,index=shard)
    assert not rows2 and counts2.get("new_stat_values",0)==0

def test_source_rate_conflict_and_absent_identity_quarantine(tmp_path):
    row=source()
    path=fixture(tmp_path,[row])
    m=match(row)
    m.stats["p1_break_point_return_win"]=0.1
    additions,why=candidate(m,row,"atp",source_match_id("atp",path,row,2)[1],path)
    assert "p1_return_break_points_converted_count" not in additions
    m2=match(row)
    m2.provider_payload={}
    assert candidate(m2,row,"atp",source_match_id("atp",path,row,2)[1],path)[1]=="lineage_rejected"

def test_writer_typed_count_exception_is_only_two_fields():
    before=match(source())
    after=deepcopy(before)
    after.stats["p1_return_break_points_converted_count"]=5
    with pytest.raises(ValueError):
        _additions(before,after)
    new=_additions(before,after,approved_count_fields=frozenset({
        "p1_return_break_points_converted_count","p2_return_break_points_converted_count"}))
    assert new=={"p1_return_break_points_converted_count":5}
    after.stats["p1_return_break_points_converted_count"]=-1
    with pytest.raises(ValueError):
        _additions(before,after,approved_count_fields=frozenset({
            "p1_return_break_points_converted_count"}))
    after.stats["p1_return_break_points_converted_count"]=5
    with pytest.raises(ValueError):
        _additions(before,after,approved_count_fields=frozenset({"p1_aces"}))
