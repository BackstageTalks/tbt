"""The read-only WTA audit must never authorize import from weak matches."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_wta2026_excel_readonly as a

def record(**kw):
    r=dict(match_id="m1",tour="wta",scheduled_at="2026-01-04T12:00:00Z",
       player1_name="Sara Bejlek",player2_name="Panna Udvardy",player1_id="p1",
       player2_id="p2",winner_id="p1",surface="Hard",tournament="ASB Classic",
       round_name="1st Round",player1_rank=None,player2_rank=87)
    r.update(kw);return r

def source(**kw):
    r=dict(Winner="Bejlek S.",Loser="Udvardy P.",Comment="Completed",
        _day="2026-01-04",Surface="Hard",Tournament="ASB Classic",
        Round="1st Round",WRank=93,LRank=87)
    r.update(kw);return r

def test_weak_name_match_never_approved():
    r=a.compare([source()],[record()])
    assert r["unique_name_day_surface_winner_DIAGNOSTIC_ONLY"]==1
    assert r["RESEARCH_rank_null_NOT_WRITEABLE"]==1
    assert r["rank_equal"]==1
    assert r["approved_added_values"]==0
    assert r["independently_attested_source_player_event_ID"]==0

def test_ambiguous_identity_quarantined():
    r=a.compare([source()],[record(),record(match_id="m2")])
    assert r["ambiguous_name_day"]==1
    assert r["approved_added_values"]==0

def test_winner_conflict_quarantined():
    r=a.compare([source()],[record(winner_id="p2")])
    assert r["winner_conflict"]==1

def test_surface_conflict_quarantined():
    r=a.compare([source()],[record(surface="Clay")])
    assert r["surface_mismatch"]==1

def test_walkovers_excluded():
    r=a.compare([source(Comment="Walkover")],[record()])
    assert r["rejected_noncompleted"]==1

def test_unaudited_workbook_rejected(tmp_path):
    p=tmp_path/"fake.xlsx";p.write_bytes(b"forged")
    with pytest.raises(ValueError,match="SOURCE_SHA256_DRIFT"):
        a.workbook_rows(p)

def test_duplicate_canonical_ids_rejected():
    with pytest.raises(ValueError,match="Duplicate or absent"):
        a.compare([source()],[record(),record()])
