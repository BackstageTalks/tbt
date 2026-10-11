"""WTA 2026 audited null-only exact-ID historical ranking writer tests."""
import json
from pathlib import Path
import sys
import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_wta2026_verified_rank_exact as m

def fixture():
    t=pd.Timestamp('2026-08-12T12:00:00Z')
    current=pd.DataFrame([
        {'match_id':'wta1','tour':'wta','scheduled_at':t,'player1_id':'c1','player2_id':'c2','player1_rank':None,'player2_rank':None,'provider_context_json':'{"existing":true}','stats_json':'{"p1_aces":1}'},
        {'match_id':'atp1','tour':'atp','scheduled_at':t,'player1_id':'a1','player2_id':'a2','player1_rank':123,'player2_rank':234,'provider_context_json':'{}','stats_json':'{}'},
    ])
    o={'canonical_match_id':'wta1','canonical_year':2026,'canonical_year_sha256':m.ORIGINAL_SHA,
       'schema':1,'status':'CANDIDATE_NOT_WRITER_APPROVED','scheduled_at':'2026-08-12T12:00:00+00:00',
       'player1_id':'c1','player2_id':'c2','source_player1_id':'wta-A','source_player2_id':'wta-B',
       'source_week_p1':'2026-08-10','source_week_p2':'2026-08-10',
       'expected_player1_rank':None,'expected_player2_rank':None,
       'add_only_null_fields':{'player1_rank':8,'player2_rank':76},
       'temporal_policy':'source_before_match_1_to_14_days'}
    return current,o

def run_one(monkeypatch,alter=None):
    monkeypatch.setattr(m,'EXPECTED_MATCHES',1)
    monkeypatch.setattr(m,'EXPECTED_VALUES',2)
    data,obs=fixture()
    if alter: alter(data,obs)
    return m.apply_exact(data,[obs])

def test_null_only_uses_strict_ids_and_preserves_atp(monkeypatch):
    original,obs=fixture()
    newer,counts=run_one(monkeypatch)
    assert counts['changed_matches']==1
    assert newer.loc[0,'player1_rank']==8 and newer.loc[0,'player2_rank']==76
    assert newer.loc[1].equals(original.loc[1])
    assert newer.loc[0,'stats_json']==original.loc[0,'stats_json']
    provenance=json.loads(newer.loc[0,'provider_context_json'])
    assert provenance['existing'] is True
    assert provenance['_tbt_rank_provenance']['source_player2_id']=='wta-B'

@pytest.mark.parametrize('alter',[
    lambda d,o: d.__setitem__('player1_rank',[50,123]),
    lambda d,o: o.__setitem__('player2_id','wrong'),
    lambda d,o: o.__setitem__('source_player2_id','wta-A'),
    lambda d,o: o.__setitem__('source_week_p1','2026-08-12'),
    lambda d,o: o.__setitem__('source_week_p1','2026-07-01'),
    lambda d,o: o.__setitem__('source_week_p1','2026-08-14'),
    lambda d,o: o['add_only_null_fields'].__setitem__('player1_rank',0),
    lambda d,o: o['add_only_null_fields'].__setitem__('player1_rank',True),
    lambda d,o: o.__setitem__('canonical_year_sha256','bad'),
    lambda d,o: o.__setitem__('temporal_policy','unchecked'),
    lambda d,o: o['add_only_null_fields'].__setitem__('stats_json',1),
    lambda d,o: d.__setitem__('provider_context_json',['{"_tbt_rank_provenance":{"source":"another"}}','{}']),
])
def test_rejects_bad_stage_or_changed_cdb(monkeypatch,alter):
    with pytest.raises((ValueError,TypeError,KeyError)):
        run_one(monkeypatch,alter)

def test_full_wta_rebase_detects_old_wta_row_change():
    old,_=fixture(); newer=old.copy(); newer.at[0,'player1_rank']=5
    with pytest.raises((ValueError,AssertionError)):
        m.attest_rebase(old,newer)

def test_stage_hash_guard(tmp_path):
    stage=tmp_path/'stage.jsonl.gz';stage.write_bytes(b'bad')
    report=tmp_path/'report.json';report.write_text('{}')
    with pytest.raises(ValueError,match='SHA'):
        m.read_stage(stage,report)
