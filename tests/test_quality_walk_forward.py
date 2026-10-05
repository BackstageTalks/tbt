import numpy as np
import pandas as pd
from audit_quality_walk_forward import year_partitions,day_cluster_delta


def test_every_annual_fold_keeps_calibration_before_test_and_training_before_calibration():
    dates=pd.date_range('2021-01-01','2026-10-04',freq='4h',tz='UTC')
    frame=pd.DataFrame({'scheduled_at':dates,'match_id':[str(i) for i in range(len(dates))],'target':np.arange(len(dates))%2})
    for year in (2023,2024,2025,2026):
        train,cal,test=year_partitions(frame,year)
        assert train.scheduled_at.max().normalize()<cal.scheduled_at.min().normalize()
        assert cal.scheduled_at.max().normalize()<test.scheduled_at.min().normalize()
        assert set(test.scheduled_at.dt.year)=={year}


def test_whole_day_bootstrap_keeps_identical_predictions_at_zero():
    y=pd.Series([0,1,1,0]);p=np.array([.2,.8,.7,.3])
    dates=pd.Series(pd.to_datetime(['2026-01-01T01:00Z','2026-01-01T02:00Z','2026-01-02T01:00Z','2026-01-02T02:00Z']))
    report=day_cluster_delta(p,p,y,dates,repetitions=100)
    assert report['day_clusters']==2
    assert report['paired_day_bootstrap_95pct_interval']==[0,0]
