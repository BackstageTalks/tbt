"""Matched chronological research on persisted causal features, no promotion.

Only serve/return inputs differ between two freshly fitted arms. Both retain
the champion's feature contract, hyperparameters, blend and calibrator family.
Model parameters and calibration parameters are fitted on separate past days.
No provider credentials, release uploads, fitted model export or selector edit.
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
from audit_high_impact import fitted_model_boundary, metrics
from release_store import ReleaseStore

QUALITY = {'serve_quality_diff', 'return_quality_diff',
    'surface_serve_quality_diff', 'surface_return_quality_diff',
    'stats_known_both', 'surface_stats_known_both', 'altitude_serve_interaction'}


def partitions(frame, boundary):
    dates = pd.to_datetime(frame.scheduled_at, utc=True, errors='coerce')
    if dates.isna().any() or frame.match_id.duplicated().any():
        raise ValueError('Invalid dates or duplicate event identities')
    if not frame.target.isin([0, 1]).all():
        raise ValueError('Invalid binary target')
    day = dates.dt.normalize()
    # Fixed windows decided before examining any held-out predictions.
    train = (day >= pd.Timestamp('2021-01-01', tz='UTC')) & (day < pd.Timestamp('2026-07-01', tz='UTC'))
    calibration = (day >= pd.Timestamp('2026-07-01', tz='UTC')) & (day < pd.Timestamp('2026-09-01', tz='UTC'))
    test = day > max(pd.Timestamp('2026-09-25', tz='UTC'), boundary.normalize())
    parts = [frame.loc[mask].copy() for mask in (train, calibration, test)]
    if min(map(len, parts)) == 0:
        raise ValueError('Empty chronological research partition')
    if any(set(parts[i].match_id) & set(parts[j].match_id) for i in range(3) for j in range(i)):
        raise ValueError('Research partitions overlap')
    return parts


def paired_delta(first, second, target):
    a,b=np.clip(first,1e-9,1-1e-9),np.clip(second,1e-9,1-1e-9)
    y=np.asarray(target,dtype=int)
    losses=lambda p: -(y*np.log(p)+(1-y)*np.log(1-p))
    difference=losses(b)-losses(a)
    se=float(difference.std(ddof=1)/np.sqrt(len(y))) if len(y)>1 else None
    mean=float(difference.mean())
    return {'n':len(y),'second_minus_first_log_loss':mean,
        'approximate_paired_95pct_interval':None if se is None else [mean-1.96*se,mean+1.96*se],
        'second_minus_first_accuracy':float(np.mean((b>=.5)==y)-np.mean((a>=.5)==y)),
        'second_minus_first_brier':float(np.mean((b-y)**2)-np.mean((a-y)**2)),
        'interval_policy':'Normal paired event approximation; correlated days/players can widen uncertainty.'}


def main():
    from sklearn.base import clone
    from tbt.models.artifact import load_model
    from tbt.models.ensemble import TennisEnsemble
    ap=argparse.ArgumentParser()
    ap.add_argument('--data-repository',default='BackstageTalks/tbt-data')
    ap.add_argument('--out',default='.cache/tbt/quality-group-ablation/report.json')
    args=ap.parse_args()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    table_dir=out.parent/'table'
    required=('training_table.parquet','training_table_report.json','leakage_audit_report.json','enrichment_summary.json')
    ReleaseStore(args.data_repository,'tbt-training-table-v1',table_dir).download(
        extra_names=required,required_names=required,require_bundle_manifest=True)
    table_report=json.loads((table_dir/'training_table_report.json').read_text())
    leakage=json.loads((table_dir/'leakage_audit_report.json').read_text())
    enrichment=json.loads((table_dir/'enrichment_summary.json').read_text())
    if leakage.get('status')!='pass' or enrichment.get('status')!='validated':
        raise ValueError('Persisted causal training DB has not passed its preflight')
    frame=pd.read_parquet(table_dir/'training_table.parquet')
    if len(frame)!=table_report.get('rows'):
        raise ValueError('Persisted row count disagrees with training table report')
    model_dir=out.parent/'champion'
    ReleaseStore(args.data_repository,'tbt-model-production-v1',model_dir).download(
        extra_names=('model.joblib','training_report.json'),required_names=('model.joblib','training_report.json'))
    champion=load_model(str(model_dir/'model.joblib'))
    boundary=fitted_model_boundary(champion.metadata)
    train,cal,test=partitions(frame,boundary)
    del frame;gc.collect()
    report={'schema':1,'purpose':'matched_group_research_not_promotion','phase':'inputs_verified',
        'generated_at':datetime.now(timezone.utc).isoformat(),'provider_requests':0,'production_mutated':False,
        'champion_version':champion.version,'test_after_fitting_boundary':str(boundary),
        'source_training_table':table_report,'source_bundle':json.loads((table_dir/ReleaseStore.BUNDLE_MANIFEST).read_text()),
        'partitions':{name:{'n':len(part),'first':str(pd.to_datetime(part.scheduled_at,utc=True).min()),
            'last':str(pd.to_datetime(part.scheduled_at,utc=True).max())} for name,part in [('train',train),('calibration',cal),('test',test)]},
        'quality_inputs':sorted(QUALITY),'fixed_choices':{'feature_names':champion.feature_names,
            'blend_weight_boost':champion.blend_weight,'elo_weight':champion.elo_weight,
            'calibrator_kind':champion.calibrator.kind},'arms':{},
        'limitations':['Retrospective research, not an untouched model promotion gate.',
            'Historical source availability cannot be certified solely from a reconstructed table.',
            'Table snapshot predates newer canonical enrichments; its row count is not a canonical loss.',
            'No odds in the table: this test measures probability quality, not yield or CLV.',
            'Diagnostic comparison of identical fitted arms isolates this group; candidate vs champion also differs in training dates.']}
    probabilities={'champion':champion.predict_proba(test)}
    report['arms']['champion']={'all_events':metrics(probabilities['champion'],test.target),
        'by_tour':{str(tour):metrics(probabilities['champion'][test.tour.to_numpy()==tour],group.target)
            for tour,group in test.groupby('tour')}}
    write=lambda:out.write_text(json.dumps(report,indent=2,allow_nan=False,default=str))
    write()
    for name,disabled in [('without_quality',QUALITY),('with_quality',set())]:
        model=TennisEnsemble(feature_names=champion.feature_names)
        model.linear=clone(champion.linear)
        model.boost=clone(champion.boost)
        model.excluded_features=set(champion.excluded_features)|disabled
        model.fit_frozen(train,cal,blend_weight=champion.blend_weight,elo_weight=champion.elo_weight,
            calibrator_kind=champion.calibrator.kind)
        probabilities[name]=model.predict_proba(test)
        variance=model.linear.named_steps['scale'].var_
        report['arms'][name]={'all_events':metrics(probabilities[name],test.target),
            'quality_training_variance':{f:float(variance[model.feature_names.index(f)]) for f in sorted(QUALITY)},
            'by_tour':{str(tour):metrics(probabilities[name][test.tour.to_numpy()==tour],group.target)
                for tour,group in test.groupby('tour')}}
        report['phase']=name;write()
        print(json.dumps({'phase':name,'test_n':len(test)}),flush=True)
        del model;gc.collect()
    known=test.stats_known_both.to_numpy()>0
    report['quality_minus_no_quality']={}
    for label,mask in [('all_events',np.ones(len(test),dtype=bool)),('quality_known',known),('quality_missing',~known)]:
        if mask.any():
            report['quality_minus_no_quality'][label]=paired_delta(probabilities['without_quality'][mask],probabilities['with_quality'][mask],test.target.to_numpy()[mask])
    report['candidate_minus_champion']=paired_delta(probabilities['champion'],probabilities['with_quality'],test.target)
    report['phase']='complete';write()
    print(json.dumps({'phase':'complete','delta':report['quality_minus_no_quality']['all_events']}),flush=True)


if __name__=='__main__':main()
