import numpy as np
import pandas as pd
import pytest
from audit_quality_group_ablation import partitions, paired_delta


def test_chronology_excludes_later_model_fitting_and_utc_boundary():
    frame=pd.DataFrame({'match_id':list('abcdef'),'target':[0,1,0,1,0,1],
        'scheduled_at':['2026-06-30T23:59Z','2026-07-01T00:00Z','2026-08-31T23:59Z',
            '2026-09-26T23:59Z','2026-09-27T00:00Z','2026-10-02T00:00Z']})
    train,cal,test=partitions(frame,pd.Timestamp('2026-09-26T20:00Z'))
    assert train.match_id.tolist()==['a']
    assert cal.match_id.tolist()==['b','c']
    assert test.match_id.tolist()==['e','f']
    with pytest.raises(ValueError,match='duplicate'):
        partitions(pd.concat([frame,frame.iloc[:1]]),pd.Timestamp('2026-09-26T20:00Z'))


def test_paired_improvement_has_correct_sign_and_identical_zero():
    y=np.array([0,1,0,1])
    same=paired_delta(np.full(4,.5),np.full(4,.5),y)
    assert same['second_minus_first_log_loss']==0
    assert same['approximate_paired_95pct_interval']==[0,0]
    better=paired_delta(np.full(4,.5),np.array([.2,.8,.2,.8]),y)
    assert better['second_minus_first_log_loss']<0
    assert better['second_minus_first_accuracy']==.5
