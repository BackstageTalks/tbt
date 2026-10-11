"""Read-only candidate counts cannot be confused with approved CDB writes."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_atp_futures_current_cdb as a


def test_preserve_link_candidate_vs_authorized_write():
    stub={"canonical_rows":994096,"production_mutated":False,"api_requests":0,
          "source_rows":27821,"counts":{"staged_matches":13,"ambiguous":2},
          "staged_field_counts":{"p1_aces":4,"p2_double_faults":3},
          "matching_strategy":"verified_ids","quality_ready_projected_added":2}
    r=a.summarized(stub,{"quarantined_rows":0},range(994096),"a"*64)
    assert r["link_staged_fields_total"]==7
    assert r["source_to_current_cdb_write_authorized"] is False
    assert r["production_cdb_mutated"] is False
    assert r["quality_ready_projected_added"]==2


def test_incomplete_canonical_or_mutating_link_fails_closed():
    stub={"canonical_rows":10,"production_mutated":False,"api_requests":0,
          "counts":{},"staged_field_counts":{}}
    with pytest.raises(ValueError):
        a.summarized(stub,{"quarantined_rows":0},range(10),"a"*64)
    stub["canonical_rows"]=994096
    stub["production_mutated"]=True
    with pytest.raises(ValueError):
        a.summarized(stub,{"quarantined_rows":0},range(994096),"a"*64)


def test_direct_id_evidence_never_authorizes_write():
    from types import SimpleNamespace
    original=("tourney_id,match_num,winner_id,loser_id\n"
              "2023-M-ITF-A,12,111,222\n").encode()
    sources=[{"source_match_id":"2023-M-ITF-A:12"}]
    stage=[{"match_id":"m1","sources":sources,"incoming_stats":{"p1_break_point_serve_win":0.5}}]
    match=SimpleNamespace(match_id="m1",player1_id="111",player2_id="222",
                          winner_id="111",provider_payload={"source":{"tourney_id":"2023-M-ITF-A","match_num":"12"}})
    r=a.strict_id_evidence(stage,original,[match])
    assert r["counts"]["source_ids_equal_canonical_ids"]==1
    assert r["counts"]["direct_id_winner_and_event_context_witness"]==1
    assert r["write_authorized"] is False
    assert r["canonical_and_source_ids_share_credentialed_namespace"] is False


def test_raw_ids_not_equal_remain_quarantined():
    from types import SimpleNamespace
    original=b"tourney_id,match_num,winner_id,loser_id\n2023-M-ITF-A,12,555,222\n"
    stage=[{"match_id":"m1","sources":[{"source_match_id":"2023-M-ITF-A:12"}],
            "incoming_stats":{"p1_break_point_serve_win":0.5}}]
    match=SimpleNamespace(match_id="m1",player1_id="111",player2_id="222",
                          winner_id="111",provider_payload={})
    r=a.strict_id_evidence(stage,original,[match])
    assert r["counts"]["raw_ids_not_equal_to_canonical_ids"]==1
    assert not r["counts"].get("direct_id_winner_event_cells")
