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
