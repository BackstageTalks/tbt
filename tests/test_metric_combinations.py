import numpy as np
import pandas as pd
from study_metric_combinations import arms, select_mix, study
from test_temporal_tour_study import FakeModel

def test_selection_prefers_baseline_on_tie_and_rejects_worse():
    y=np.array([0,1,0,1]);p=np.array([.2,.8,.2,.8])
    assert select_mix(y,{'baseline':p,'other':p})=={'baseline':1.}
    assert select_mix(y,{'baseline':p,'other':1-p})=={'baseline':1.}

def test_test_labels_do_not_change_weights(tmp_path):
    dates=pd.date_range('2024-01-01','2025-03-31',freq='D',tz='UTC').repeat(20)
    n=len(dates);frame=pd.DataFrame({k:np.zeros(n) for names in arms().values() for k in names})
    frame['scheduled_at']=dates;frame['match_id']=np.arange(n);frame['target']=np.arange(n)%2;frame['tour_atp']=(np.arange(n)//2)%2
    a=study(frame,tmp_path/'a.json',FakeModel,starts=['2025-01-01'])
    frame.loc[frame.scheduled_at>='2025-01-01','target']^=1
    b=study(frame,tmp_path/'b.json',FakeModel,starts=['2025-01-01'])
    assert a['folds'][0]['choices']==b['folds'][0]['choices']
    assert a['folds'][0]['groups']['all']['baseline']['accuracy']==1
    assert b['folds'][0]['groups']['all']['baseline']['accuracy']==0


def test_protected_workflow_persists_and_validates_real_metric_report():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/protected-frozen-cdb-candidate.yml').read_text(encoding='utf-8')
    research = workflow.split('- name: Research temporal ATP/WTA variants on verified inputs', 1)[1].split('- name:', 1)[0]
    assert 'tests/test_metric_combinations.py' in research
    assert "test -s .cache/tbt/training-backup/metric-combinations.json" in research
    assert "d['status']=='COMPLETED_RESEARCH_ONLY'" in research
    assert "d.get('verified_backup',{}).get('remote_manifest_sha256')" in research
    upload = workflow.split('- name: Persist non-sensitive run proof as GitHub artifact', 1)[1].split('- name:', 1)[0]
    assert '.cache/tbt/training-backup/metric-combinations.json' in upload
    assert 'if: always()' in upload
