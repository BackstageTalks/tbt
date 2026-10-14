"""Synthetic adversarial checks: native lineage is exact, no fuzzy import."""
from __future__ import annotations
import json
from datetime import datetime, timezone

from scripts.audit_source_value_routes import historical_id
from scripts.stage_sackmann_native_breakpoints import check_exact, rate

def fixture():
    row = {
        "tourney_id": "2024-123", "tourney_date": "20240115", "match_num": "1",
        "round": "F", "score": "6-4 6-3", "best_of": "3",
        "winner_name": "Novak Djokovic", "loser_name": "Jannik Sinner",
        "winner_id": "104925", "loser_id": "126774"
    }
    for side in ("w", "l"):
        row.update({
            side+"_svpt": "60", side+"_SvGms": "10",
            side+"_1stIn": "40", side+"_1stWon": "30",
            side+"_2ndWon": "10", side+"_ace": "5", side+"_df": "2",
            side+"_bpSaved": "3" if side == "w" else "4",
            side+"_bpFaced": "4" if side == "w" else "6",
        })
    rel = "atp/atp_matches_2024.csv"
    mid,_ = historical_id("atp", rel, row)
    candidate = {
        "tour": "atp", "source_file": rel,
        "source_native_key": ["atp","2024-123","20240115","1","F","104925","126774"],
        "missing_candidate_cells": {
            "p1_break_point_return_win": (6-4)/6,
            "p2_break_point_return_win": (4-3)/4,
        }
    }
    canon = {
        "match_id": mid, "tour": "atp", "status": "completed",
        "scheduled_at": datetime(2024,1,15,tzinfo=timezone.utc),
        "player1_id": "hist-js:atp:104925", "player2_id": "hist-js:atp:126774",
        "player1_name": "Novak Djokovic", "player2_name": "Jannik Sinner",
        "winner_id": "hist-js:atp:104925",
        "stats_json": json.dumps({"p1_aces":5,"p2_aces":5}),
        "provider_context_json": json.dumps({
            "_tbt_statistics": {"source":"jeff_sackmann_match_snapshot:atp_matches_2024.csv"},
            "_tbt_source_category_name":"historical_main",
            "_tbt_provider_event_id": mid,
        }),
    }
    return candidate,row,canon

def test_exact_original_native_rehydration_only():
    c,r,m=fixture()
    v,reason=check_exact(c,r,m)
    assert not reason
    assert v==c["missing_candidate_cells"]

def test_same_name_wrong_original_player_id_fails_closed():
    c,r,m=fixture()
    m["player1_id"]="hist-js:atp:999999"
    assert check_exact(c,r,m)[1]=="player_identity_or_winner_mismatch"

def test_lineage_metadata_proves_original_source():
    c,r,m=fixture()
    context=json.loads(m["provider_context_json"])
    context["_tbt_statistics"]["source"]="unknown-other-provider"
    m["provider_context_json"]=json.dumps(context)
    assert check_exact(c,r,m)[1]=="provenance_mismatch"

def test_reused_match_id_with_date_conflict_rejected():
    c,r,m=fixture()
    m["scheduled_at"]=datetime(2024,1,16,tzinfo=timezone.utc)
    assert check_exact(c,r,m)[1]=="date_mismatch"

def test_no_overwrite_and_candidate_cell_mismatch():
    c,r,m=fixture()
    m["stats_json"]='{"p1_break_point_return_win":0.99}'
    assert check_exact(c,r,m)[1]=="no_longer_null"
    c,r,m=fixture()
    c["missing_candidate_cells"]["p2_break_point_return_win"]=0.123
    assert check_exact(c,r,m)[1]=="candidate_source_value_mismatch"

def test_full_score_required_and_no_undefined_zero_break_points():
    c,r,m=fixture()
    r["score"]="6-4 RET"
    assert check_exact(c,r,m)[1]=="incomplete_or_invalid_full_match"
    assert rate(0,0) is None
    assert rate(0,2)==1.0
    assert rate(2,2)==0.0
    assert rate(3,2) is None

def test_research_only_field_whitelist_and_status():
    c,r,m=fixture()
    c["missing_candidate_cells"]={"p1_break_points_won":1}
    assert check_exact(c,r,m)[1]=="unexpected_external_field"
    c,r,m=fixture()
    m["status"]="upcoming"
    assert check_exact(c,r,m)[1]=="match_not_completed"
