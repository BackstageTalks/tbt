from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_issued_categories import analyze


def publication(section='ace', **values):
    return {'section':section,'market':'aces','selection_id':'A','issued_at':'2026-10-03T08:00:00Z',
            'publication_status':'published','projection_scope':'player','projection_metric':'aces',
            'odds':2.,'offer_position':1,'result':{'correct':True},**values}


def test_all_categories_deduplicate_and_never_count_retirement_as_win():
    pub = publication()
    rows = [{'event_id':'x','scheduled_at':'2026-10-03T12:00:00Z','market_publications':[pub,dict(pub)]},
            {'event_id':'y','scheduled_at':'2026-10-03T12:00:00Z','market_publications':[publication(result={'status':'retired','correct':True})]},
            {'event_id':'z','scheduled_at':'2026-10-03T12:00:00Z','market_publications':[publication('double_faults',odds=None,result={'correct':False})]}]
    report=analyze(rows,now=datetime(2026,10,4,tzinfo=timezone.utc))
    ace=report['sections']['ace']
    assert ace['overall']['settled']==1
    assert ace['overall']['yield_flat_stake']==1
    assert ace['void']==1
    assert report['diagnostics']['duplicate_issued_identity']==1
    df=report['sections']['double_faults']['overall']
    assert df['settled']==1 and df['priced']==0 and df['yield_flat_stake'] is None
    assert df['yield_small_sample'] is True
    assert df['yield_ci95_normal_approximation'] is None


def test_missing_offer_position_is_not_assigned_into_membership_scenario():
    rows=[{'event_id':'x','scheduled_at':'2026-10-03T12:00:00Z','market_publications':[publication(offer_position=None)]}]
    section=analyze(rows,now=datetime(2026,10,4,tzinfo=timezone.utc))['sections']['ace']
    assert section['overall']['settled']==1
    assert section['immutable_position_missing']==1
    assert section['first_n_offer_position_scenarios']['5']['settled']==0
