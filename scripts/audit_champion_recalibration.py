"""Isolate recalibration-only on frozen champion; no production writes."""
import argparse
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import pandas as pd
from _bootstrap import ROOT
from release_store import ReleaseStore
from audit_high_impact import fitted_model_boundary,metrics
from audit_quality_group_ablation import partitions,paired_delta


def main():
    from tbt.models.artifact import load_model
    ap=argparse.ArgumentParser();ap.add_argument('--data-repository',default='BackstageTalks/tbt-data')
    ap.add_argument('--out',default='.cache/tbt/champion-recalibration/report.json');args=ap.parse_args()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);root=out.parent/'table'
    required=('training_table.parquet','training_table_report.json','leakage_audit_report.json','enrichment_summary.json')
    ReleaseStore(args.data_repository,'tbt-training-table-v1',root).download(extra_names=required,required_names=required,require_bundle_manifest=True)
    if json.loads((root/'leakage_audit_report.json').read_text()).get('status')!='pass' or json.loads((root/'enrichment_summary.json').read_text()).get('status')!='validated':raise ValueError('Unverified causal table')
    frame=pd.read_parquet(root/'training_table.parquet')
    if len(frame)!=json.loads((root/'training_table_report.json').read_text()).get('rows'):raise ValueError('Table row-count mismatch')
    model_root=out.parent/'model'
    ReleaseStore(args.data_repository,'tbt-model-production-v1',model_root).download(extra_names=('model.joblib','training_report.json'),required_names=('model.joblib','training_report.json'))
    champion=load_model(str(model_root/'model.joblib'));boundary=fitted_model_boundary(champion.metadata)
    _,cal,test=partitions(frame,boundary)
    altered=copy.deepcopy(champion)
    # Same predeclared July/August calibration window as matched retrain test.
    # Existing base estimators/blends and calibrator family remain fixed.
    altered.calibrator=altered._fit_calibrator(champion.calibrator.kind,champion._raw(cal),cal.target.to_numpy())
    old=champion.predict_proba(test);new=altered.predict_proba(test)
    report={'schema':1,'phase':'complete','generated_at':datetime.now(timezone.utc).isoformat(),
        'provider_requests':0,'production_mutated':False,'model_version':champion.version,
        'source_table_bundle':json.loads((root/ReleaseStore.BUNDLE_MANIFEST).read_text()),
        'evaluation_boundary':str(boundary),'calibrator_kind':champion.calibrator.kind,
        'calibration':{'n':len(cal),'first':str(pd.to_datetime(cal.scheduled_at,utc=True).min()),'last':str(pd.to_datetime(cal.scheduled_at,utc=True).max())},
        'test':{'n':len(test),'first':str(pd.to_datetime(test.scheduled_at,utc=True).min()),'last':str(pd.to_datetime(test.scheduled_at,utc=True).max())},
        'champion':metrics(old,test.target),'recalibration_only':metrics(new,test.target),
        'recalibration_minus_champion':paired_delta(old,new,test.target),
        'policy':'Retrospective diagnostic, not an untouched promotion gate. Freeze base estimators, blend/Elo weights, feature contract and calibrator family. Only calibrator parameters fit on the predeclared past July/August window change. No model export, selection rule or production mutation.'}
    out.write_text(json.dumps(report,indent=2,allow_nan=False,default=str))
    print(json.dumps({'phase':'complete','delta':report['recalibration_minus_champion']}),flush=True)


if __name__=='__main__':main()
