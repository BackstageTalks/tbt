"""Read-only older WTA ranking snapshots require attested IDs and 1-14 day PIT."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
import pytest
import audit_wta_2023_2024_verified_rank_gaps as a

SHA="f"*64

def match(year, p1=None, p2=None):
    return SimpleNamespace(match_id=f"wta-{year}", tour="wta",
        scheduled_at=datetime(year,8,10,12,tzinfo=timezone.utc),
        player1_id="canon-A",player2_id="canon-B",player1_name="One",
        player2_name="Two",player1_rank=p1,player2_rank=p2)

class Source:
    def __init__(self, year, mapping=None, age=7):
        self._canonical_to_sackmann={"canon-A":"s1","canon-B":"s2"} if mapping is None else mapping
        self.date=date(year,8,10).fromordinal(date(year,8,10).toordinal()-age)
    def _snapshot(self,name,day,*,player_id,max_age_days):
        return {"date":self.date,"rank":12 if player_id=="canon-A" else 34}

@pytest.mark.parametrize("year",[2023,2024])
def test_exact_source_id_prior_week_and_two_nulls(monkeypatch,year):
    monkeypatch.setattr(a,"YEAR",year)
    report,stage=a.audit_rows([match(year)],Source(year),SHA,{})
    assert report["year"]==year
    assert report["status"]==f"READ_ONLY_WTA{year}_ID_RANK_CDB_GAPS"
    assert report["counts"]["candidate_rank_cells"]==2
    assert stage[0]["canonical_year"]==year
    assert stage[0]["add_only_null_fields"]=={"player1_rank":12,"player2_rank":34}
    assert report["write_authorized"] is False

@pytest.mark.parametrize("year",[2023,2024])
def test_no_overwrite_conflicting_original_rank(monkeypatch,year):
    monkeypatch.setattr(a,"YEAR",year)
    report,stage=a.audit_rows([match(year,p1=99)],Source(year),SHA,{})
    assert stage==[]
    assert report["quarantined"]["existing_rank_disagreement"]==1

@pytest.mark.parametrize("year",[2023,2024])
@pytest.mark.parametrize("age",[0,-1,15])
def test_future_same_day_and_stale_rejected(monkeypatch,year,age):
    monkeypatch.setattr(a,"YEAR",year)
    report,stage=a.audit_rows([match(year)],Source(year,age=age),SHA,{})
    assert stage==[]
    assert report["quarantined"]["future_same_day_or_stale_rank"]==1

@pytest.mark.parametrize("year",[2023,2024])
def test_source_id_one_to_one(monkeypatch,year):
    monkeypatch.setattr(a,"YEAR",year)
    report,stage=a.audit_rows([match(year)],Source(year,{"canon-A":"s","canon-B":"s"}),SHA,{})
    assert stage==[]
    assert report["quarantined"]["missing_or_nonunique_player_ids"]==1
