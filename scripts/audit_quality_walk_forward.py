"""Read-only annual quality ablation; all fitting/selection precedes each year.

Unlike the fixed current-champion comparison, historical folds choose their
blend/calibrator only on that fold's past calibration period. Never promote.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import numpy as np
import pandas as pd
from _bootstrap import ROOT
from audit_high_impact import metrics
from audit_quality_group_ablation import QUALITY, paired_delta
from release_store import ReleaseStore


def year_partitions(frame, year):
    days=pd.to_datetime(frame.scheduled_at,utc=True,errors='coerce').dt.normalize()
    if days.isna().any() or frame.match_id.duplicated().any():
        raise ValueError('Invalid event dates or duplicate event identities')
    if not frame.target.isin([0,1]).all():raise ValueError('Invalid binary targets')
    start=pd.Timestamp(f'{year}-01-01',tz='UTC')
    cal_start=pd.Timestamp(f'{year-1}-11-01',tz='UTC')
    end=pd.Timestamp(f'{year+1}-01-01',tz='UTC')
    masks=[(days>=pd.Timestamp('2021-01-01',tz='UTC'))&(days<cal_start),
        (days>=cal_start)&(days<start),(days>=start)&(days<end)]
    result=[frame.loc[mask].copy() for mask in masks]
    if min(map(len,result))<300:raise ValueError('Annual fold requires >=300 events in each partition')
    return result


def day_cluster_delta(first,second,target,dates,repetitions=1000):
    report=paired_delta(first,second,target)
    y=np.asarray(target,dtype=int)
    a,b=np.clip(first,1e-9,1-1e-9),np.clip(second,1e-9,1-1e-9)
    difference=-(y*np.log(b)+(1-y)*np.log(1-b))+(y*np.log(a)+(1-y)*np.log(1-a))
    grouped=pd.DataFrame({'difference':difference,'day':pd.to_datetime(dates,utc=True).dt.normalize().to_numpy()}).groupby('day').difference.agg(['sum','count'])
    rng=np.random.default_rng(20261005)
    sampled=rng.integers(0,len(grouped),size=(repetitions,len(grouped)))
    means=grouped['sum'].to_numpy()[sampled].sum(axis=1)/grouped['count'].to_numpy()[sampled].sum(axis=1)
    report['day_clusters']=len(grouped)
    report['paired_day_bootstrap_95pct_interval']=np.quantile(means,[.025,.975]).tolist()
    report['bootstrap_policy']='Event-weighted mean after resampling whole UTC days; adjacent-day/player dependence and multiple explored segments remain limitations.'
    return report


def main():
    from tbt.models.artifact import load_model
    from tbt.models.ensemble import TennisEnsemble
    from sklearn.base import clone
    ap=argparse.ArgumentParser()
    ap.add_argument('--data-repository',default='BackstageTalks/tbt-data')
    ap.add_argument('--out',default='.cache/tbt/quality-walk-forward/report.json')
    args=ap.parse_args();out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    root=out.parent/'table'
    required=('training_table.parquet','training_table_report.json','leakage_audit_report.json','enrichment_summary.json')
    ReleaseStore(args.data_repository,'tbt-training-table-v1',root).download(extra_names=required,required_names=required,require_bundle_manifest=True)
    table_report=json.loads((root/'training_table_report.json').read_text())
    if json.loads((root/'leakage_audit_report.json').read_text()).get('status')!='pass' or json.loads((root/'enrichment_summary.json').read_text()).get('status')!='validated':
        raise ValueError('Unverified training DB')
    frame=pd.read_parquet(root/'training_table.parquet')
    if len(frame)!=table_report.get('rows'):raise ValueError('Persisted table row-count mismatch')
    model_root=out.parent/'schema'
    ReleaseStore(args.data_repository,'tbt-model-production-v1',model_root).download(extra_names=('model.joblib','training_report.json'),required_names=('model.joblib','training_report.json'))
    schema_model=load_model(str(model_root/'model.joblib'))
    report={'schema':1,'phase':'inputs_verified','generated_at':datetime.now(timezone.utc).isoformat(),
        'purpose':'retrospective_annual_ablation_not_promotion','provider_requests':0,'production_mutated':False,
        'source_bundle':json.loads((root/ReleaseStore.BUNDLE_MANIFEST).read_text()),
        'source_rows':len(frame),'feature_contract_reference':schema_model.version,'folds':[],
        'policy':'Train from 2021 before preceding November; calibration in preceding November/December; test only next calendar year. Both arms clone identical estimator hyperparameters and select blends/calibration on past fold data only.',
        'limitations':['Retrospective reconstructed dataset, not previously untouched promotion evidence.',
            'Champion estimator family/feature contract retained, but its later blend weights/calibrator choice are NOT used for earlier folds.',
            'Weather excluded; no new external seasonal inputs; no prices, yield or CLV available in this table.',
            'Sparse, correlated and repeatedly explored segments require new prospective confirmation.']}
    write=lambda:out.write_text(json.dumps(report,indent=2,allow_nan=False,default=str))
    write();combined=[]
    for year in (2023,2024,2025,2026):
        train,cal,test=year_partitions(frame,year)
        fold={'year':year,'partitions':{name:{'n':len(part),'first':str(pd.to_datetime(part.scheduled_at,utc=True).min()),'last':str(pd.to_datetime(part.scheduled_at,utc=True).max())} for name,part in [('train',train),('calibration',cal),('test',test)]},'arms':{}}
        predictions={}
        for name,disabled in [('without_quality',QUALITY),('with_quality',set())]:
            model=TennisEnsemble(feature_names=schema_model.feature_names,objective='log_loss')
            model.linear=clone(schema_model.linear);model.boost=clone(schema_model.boost)
            model.excluded_features=set(schema_model.excluded_features)|disabled
            model.fit(train,cal)
            p=model.predict_proba(test);predictions[name]=p
            fold['arms'][name]={'metrics':metrics(p,test.target),'fitted_choices':model.metadata,
                'quality_training_variance':{f:float(model.linear.named_steps['scale'].var_[model.feature_names.index(f)]) for f in sorted(QUALITY)}}
            del model;gc.collect()
        fold['quality_minus_no_quality']=day_cluster_delta(predictions['without_quality'],predictions['with_quality'],test.target,test.scheduled_at)
        report['folds'].append(fold);report['phase']=f'year_{year}';write()
        combined.append(test[['target','scheduled_at','tour','surface','stats_known_both','data_depth']].assign(with_quality=predictions['with_quality'],without_quality=predictions['without_quality']))
        print(json.dumps({'year':year,'delta':fold['quality_minus_no_quality']}),flush=True)
        del train,cal,test;gc.collect()
    joined=pd.concat(combined,ignore_index=True)
    def compare(group):
        return {'with_quality':metrics(group.with_quality,group.target),'without_quality':metrics(group.without_quality,group.target),
            'quality_minus_no_quality':day_cluster_delta(group.without_quality,group.with_quality,group.target,group.scheduled_at)}
    report['overall']=compare(joined)
    report['by_tour']={str(k):compare(g) for k,g in joined.groupby('tour')}
    report['by_surface']={str(k):compare(g) for k,g in joined.groupby('surface')}
    report['by_quality_availability']={str(k):compare(g) for k,g in joined.groupby(joined.stats_known_both>0)}
    report['phase']='complete';write()
    print(json.dumps({'phase':'complete','n':len(joined),'delta':report['overall']['quality_minus_no_quality']}),flush=True)


if __name__=='__main__':main()
