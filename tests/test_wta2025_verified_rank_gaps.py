"""Strict ID-only WTA historical rank gap stage remains read-only."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
import pytest
from audit_wta2025_verified_rank_gaps import audit_rows

SHA="a"*64

def match(mid="m1",p1=None,p2=None):
    return SimpleNamespace(match_id=mid,tour="wta",
        scheduled_at=datetime(2025,8,10,12,tzinfo=timezone.utc),
        player1_id="a",player2_id="b",
        player1_name="Alpha",player2_name="Beta",
        player1_rank=p1,player2_rank=p2)

class Rank:
    def __init__(self,mapping=None,week=date(2025,8,3)):
        self._canonical_to_sackmann={"a":"A","b":"B"} if mapping is None else mapping
        self.week=week
    def _snapshot(self,name,day,*,player_id,max_age_days):
        return {"date":self.week,"rank":21 if player_id=="a" else 35}

def test_both_missing_exact_ids_have_two_add_only_values():
    report,stage=audit_rows([match()],Rank(),SHA,{"source":"b"*64})
    assert report["counts"]["candidate_rank_cells"]==2
    assert stage[0]["add_only_null_fields"]=={"player1_rank":21,"player2_rank":35}
    assert not report["write_authorized"] and not report["canonical_mutated"]

def test_preexisting_matching_rank_preserved_and_other_filled():
    report,stage=audit_rows([match(p1=21)],Rank(),SHA,{})
    assert len(stage)==1 and stage[0]["add_only_null_fields"]=={"player2_rank":35}

def test_preexisting_rank_disagreement_quarantined():
    report,stage=audit_rows([match(p1=99)],Rank(),SHA,{})
    assert stage==[]
    assert report["quarantined"]["existing_rank_disagreement"]==1

@pytest.mark.parametrize("mapping",[
    {"a":"A"}, {"a":"A","b":"A"}, {"a":"A","b":"B","c":"B"}
])
def test_unverified_or_ambiguous_id_never_falls_back_to_name(mapping):
    report,stage=audit_rows([match()],Rank(mapping),SHA,{})
    assert stage==[] and report["quarantined"]["missing_or_nonunique_player_ids"]==1

@pytest.mark.parametrize("week",[
    date(2025,8,10),date(2025,7,20),date(2025,8,11)
])
def test_same_day_future_or_stale_week_fails_closed(week):
    report,stage=audit_rows([match()],Rank(week=week),SHA,{})
    assert stage==[] and report["quarantined"]["future_same_day_or_stale_rank"]==1

def test_duplicate_canonical_match_id_refused():
    with pytest.raises(ValueError,match="Duplicate"):
        audit_rows([match(),match()],Rank(),SHA,{})
