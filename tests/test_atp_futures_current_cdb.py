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


def test_atp_futures_name_linked_candidates_are_not_verified_id_imports():
    source = {
        "canonical_rows": 994096, "production_mutated": False, "api_requests": 0,
        "source_rows": 27821,
        "counts": {"staged_matches": 321, "identity_linked": 12131,
                   "name_linked": 12131, "verified_id_linked": 0},
        "staged_field_counts": {"p1_break_point_return_win": 321,
                                "p1_break_point_serve_win": 299,
                                "p2_break_point_return_win": 299,
                                "p2_break_point_serve_win": 321},
        "matching_strategy": "verified_ids",
        "verified_crosswalk_sha256": None,
        "quality_ready_projected_added": 0,
    }
    evidence = a.summarized(source, {"quarantined_rows": 0}, range(994096), "a" * 64)
    assert evidence["link_staged_fields_total"] == 1240
    assert evidence["name_only_linked_source_rows"] == 12131
    assert evidence["verified_id_linked_source_rows"] == 0
    assert evidence["identity_verified_candidate_fields"] == 0
    assert evidence["write_approved_statistic_values"] == 0
    assert evidence["source_to_current_cdb_write_authorized"] is False
    assert evidence["identity_provenance"] == "NAME_MATCHED_CANDIDATES_ONLY_NO_VERIFIED_ID_CROSSWALK"


def test_futures_does_not_accept_unsupported_verified_id_claim():
    source = {
        "canonical_rows": 994096, "production_mutated": False, "api_requests": 0,
        "counts": {"identity_linked": 1, "verified_id_linked": 1, "name_linked": 0},
        "staged_field_counts": {}, "verified_crosswalk_sha256": None,
    }
    with pytest.raises(ValueError, match="without SHA-pinned"):
        a.summarized(source, {"quarantined_rows": 0}, range(994096), "a" * 64)


def test_futures_rejects_unattributed_linked_identity_counts():
    source = {
        "canonical_rows": 994096, "production_mutated": False, "api_requests": 0,
        "counts": {"identity_linked": 5, "verified_id_linked": 1, "name_linked": 1},
        "staged_field_counts": {}, "verified_crosswalk_sha256": "a" * 64,
    }
    with pytest.raises(ValueError, match="Incomplete linker identity attribution"):
        a.summarized(source, {"quarantined_rows": 0}, range(994096), "a" * 64)



def test_existing_verified_player_sidecar_bridge_is_only_diagnostic():
    from types import SimpleNamespace
    original = ("tourney_id,match_num,winner_id,loser_id\n"
                "2024-M-ITF-X,12,123456,987654\n").encode()
    staged = [{"match_id": "m1",
               "sources": [{"source_match_id": "2024-M-ITF-X:12"}],
               "incoming_stats": {"p1_break_point_serve_win": 0.5,
                                  "p2_break_point_return_win": 0.42}}]
    match = SimpleNamespace(match_id="m1", player1_id="11", player2_id="22",
                            winner_id="11")
    approved = "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb"
    rows = [{"tour": "atp", "source_player_id": "hist-js:atp:123456",
             "canonical_player_id": "11", "evidence": approved},
            {"tour": "atp", "source_player_id": "hist-js:atp:987654",
             "canonical_player_id": "22", "evidence": approved}]
    report = a.existing_identity_sidecar_diagnostic(staged, original, [match], rows)
    assert report["known_verified_atp_sidecar_links"] == 2
    assert report["counts"]["hypothetical_full_player_pair_and_winner_equal"] == 1
    assert report["counts"]["hypothetical_candidate_statistic_cells"] == 2
    assert report["original_raw_source_player_id_namespace_independently_attested_as_sackmann"] is False
    assert report["new_verifiable_write_approved_fields"] == 0
    assert report["source_to_current_cdb_write_authorized"] is False


def test_existing_player_sidecar_never_accepts_identity_collision_or_fake_proof():
    from types import SimpleNamespace
    original = b"tourney_id,match_num,winner_id,loser_id\nX,1,111,222\n"
    staged = [{"match_id": "m", "sources": [{"source_match_id": "X:1"}],
               "incoming_stats": {"p1_aces": 1}}]
    match = SimpleNamespace(match_id="m", player1_id="a", player2_id="b",
                            winner_id="a")
    approved = "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb"
    row = {"tour": "atp", "source_player_id": "hist-js:atp:111",
           "canonical_player_id": "a", "evidence": approved}
    with pytest.raises(ValueError, match="Non-unique"):
        a.existing_identity_sidecar_diagnostic(staged, original, [match], [row, row])
    with pytest.raises(ValueError, match="untrusted identity"):
        a.existing_identity_sidecar_diagnostic(
            staged, original, [match], [{**row, "evidence": "name_only"}])


def test_existing_player_sidecar_blocks_wrong_winner_and_unmapped_opponent():
    from types import SimpleNamespace
    raw = b"tourney_id,match_num,winner_id,loser_id\nX,2,333,444\n"
    stages = [{"match_id": "m", "sources": [{"source_match_id": "X:2"}],
               "incoming_stats": {"p1_aces": 1}}]
    match = SimpleNamespace(match_id="m", player1_id="a", player2_id="b",
                            winner_id="a")
    approved = "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb"
    rows = [{"tour": "atp", "source_player_id": "hist-js:atp:333",
             "canonical_player_id": "b", "evidence": approved},
            {"tour": "atp", "source_player_id": "hist-js:atp:444",
             "canonical_player_id": "a", "evidence": approved}]
    r = a.existing_identity_sidecar_diagnostic(stages, raw, [match], rows)
    assert r["counts"]["full_pair_winner_conflict"] == 1
    assert not r["counts"].get("hypothetical_candidate_statistic_cells")
    r = a.existing_identity_sidecar_diagnostic(stages, raw, [match], rows[:1])
    assert r["counts"]["at_least_one_player_missing_crosswalk"] == 1
    assert r["new_verifiable_write_approved_fields"] == 0
