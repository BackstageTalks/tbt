from datetime import date, datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from scripts.audit_wta_official_2026_gaps import inspect

def match(r1=None,r2=None,when="2026-07-14T12:00:00"):
    return SimpleNamespace(match_id="m1",tour="wta",
        scheduled_at=datetime.fromisoformat(when).replace(tzinfo=timezone.utc),
        player1_id="100",player2_id="200",
        player1_name="Jane Doe",player2_name="Lucy Example",
        player1_rank=r1,player2_rank=r2)

def source(when="2026-07-13",r1=12,r2=38):
    d=date.fromisoformat(when)
    return {(d,"100"):(r1,"jane doe",True),(d,"200"):(r2,"lucy example",True)}

def test_adds_only_missing_from_prior_week():
    original=match()
    rows,counts=inspect([original],source())
    assert len(rows)==1 and counts["missing_rank_values"]==2
    assert rows[0]["proposed"]==[12,38] and rows[0]["candidate_only"]
    assert original.player1_rank is None

def test_existing_rank_mismatch_blocks_entire_match():
    rows,counts=inspect([match(13,None)],source())
    assert not rows and counts["existing_conflict"]==1

def test_one_sided_agreement():
    rows,counts=inspect([match(12,None)],source())
    assert len(rows)==1 and counts["missing_rank_values"]==1

def test_future_same_day_and_stale_week_never_apply():
    for when in ("2026-07-14","2026-07-20","2026-07-05"):
        rows,counts=inspect([match()],source(when))
        assert not rows

def test_unknown_id_namespace_needs_matching_name():
    data=source()
    for key,(rank,name,_) in list(data.items()):
        data[key]=(rank,"",False)
    rows,counts=inspect([match()],data)
    assert not rows and counts["missing_identity_or_rank"]==1

def test_player_name_disagreement_rejected():
    data=source(); data[(date(2026,7,13),"100")]=(12,"wrong name",True)
    rows,counts=inspect([match()],data)
    assert not rows and counts["missing_identity_or_rank"]==1

def test_rank_week_mismatch_rejected():
    data=source()
    data.pop((date(2026,7,13),"200"))
    data[(date(2026,7,6),"200")]=(38,"lucy example",True)
    rows,counts=inspect([match()],data)
    assert not rows and counts["rank_week_conflict"]==1

def test_read_only_audit_code_contract():
    code=(Path(__file__).resolve().parents[1]/"scripts/audit_wta_official_2026_gaps.py").read_text()
    assert "write_year_partition" not in code and "upload_bundle" not in code
    assert '"write_authorized":False' in code and '"model_promoted":False' in code
