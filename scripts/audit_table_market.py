"""Compare a verified causal training-table slice with a checksum-pinned year.

Unrelated historical partitions need not be downloaded or used. Every file
actually consumed is checksum-verified; production ReleaseStore is unchanged.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import pandas as pd
from _bootstrap import ROOT
from release_store import ReleaseStore
from audit_high_impact import fitted_model_boundary,metrics
from audit_existing_data_value import align_market,comparison,grouped
from tbt.data.history_snapshot import load_snapshot
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_market_history import clean_market_history_marker
from tbt.models.feature_builder import FeatureBuilder


def download_verified_year(store,year):
    name=f'history-{int(year):04d}.parquet'
    if not re.fullmatch(r'history-\d{4}\.parquet',name):raise ValueError('Invalid year')
    required={name,'history_manifest.json',store.BUNDLE_MANIFEST}
    if not required.issubset(store._asset_names()):raise FileNotFoundError('Missing scoped history evidence')
    store._download_asset(store.BUNDLE_MANIFEST)
    bundle=json.loads((store.directory/store.BUNDLE_MANIFEST).read_text())
    files=bundle.get('files',{})
    for asset in (name,'history_manifest.json'):
        expected=(files.get(asset) or {}).get('sha256')
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
            raise ValueError('Requested history evidence lacks checksum coverage')
        store._download_asset(asset)
        if store._sha256(store.directory/asset)!=expected:
            raise ValueError('Scoped history checksum mismatch: '+asset)
    manifest=json.loads((store.directory/'history_manifest.json').read_text())
    entry=manifest.get('years',{}).get(str(year),{})
    if entry.get('asset')!=name or entry.get('sha256')!=files[name]['sha256']:
        raise ValueError('Partition and history manifests disagree')
    return store.directory/name,bundle,entry


def aligned_event(row,match):
    oriented,target=FeatureBuilder.orient_for_training(match)
    return (int(row['target'])==target
        and pd.Timestamp(row['scheduled_at'])==pd.Timestamp(match.scheduled_at)
        and str(row['tour']).lower()==match.tour.lower()
        and str(row['surface'])==str(match.surface))


def main():
    from tbt.models.artifact import load_model
    from tbt.services.training import _verified_rank_provenance
    ap=argparse.ArgumentParser();ap.add_argument('--data-repository',default='BackstageTalks/tbt-data')
    ap.add_argument('--out',default='.cache/tbt/table-market/report.json');args=ap.parse_args()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True);root=out.parent/'table'
    required=('training_table.parquet','training_table_report.json','leakage_audit_report.json','enrichment_summary.json')
    ReleaseStore(args.data_repository,'tbt-training-table-v1',root).download(extra_names=required,required_names=required,require_bundle_manifest=True)
    table_report=json.loads((root/'training_table_report.json').read_text())
    if json.loads((root/'leakage_audit_report.json').read_text()).get('status')!='pass' or json.loads((root/'enrichment_summary.json').read_text()).get('status')!='validated':raise ValueError('Unverified causal table')
    frame=pd.read_parquet(root/'training_table.parquet')
    if len(frame)!=table_report.get('rows') or frame.match_id.duplicated().any():raise ValueError('Table identity/row-count disagreement')
    model_root=out.parent/'model'
    ReleaseStore(args.data_repository,'tbt-model-production-v1',model_root).download(extra_names=('model.joblib','training_report.json'),required_names=('model.joblib','training_report.json'))
    model=load_model(str(model_root/'model.joblib'));boundary=fitted_model_boundary(model.metadata)
    frame=frame.loc[pd.to_datetime(frame.scheduled_at,utc=True).dt.normalize()>boundary.normalize()].copy()
    report={'schema':1,'phase':'inputs_verified','generated_at':datetime.now(timezone.utc).isoformat(),
        'provider_requests':0,'production_mutated':False,'model_version':model.version,'evaluation_boundary':str(boundary),
        'causal_table_bundle':json.loads((root/ReleaseStore.BUNDLE_MANIFEST).read_text()),
        'table_date_range':table_report.get('date_range'),'scoped_history':{},
        'all_post_fitting_events':metrics(model.predict_proba(frame),frame.target),'policy':'Only whole UTC days after final model fitting and availability. Independent fitting period, but retrospective and not an untouched promotion gate. Opening/closing are source labels without independently verified tick times; no measured CLV. Canonical year and older causal table are explicitly different snapshots: joined events must agree on ID, timestamp, target, tour and surface.'}
    canonical={}
    for year in sorted(pd.to_datetime(frame.scheduled_at,utc=True).dt.year.unique()):
        partition,bundle,entry=download_verified_year(ReleaseStore(args.data_repository,'tbt-data-v1',out.parent/f'history-{year}'),int(year))
        matches=load_snapshot(partition)
        if len(matches)!=entry.get('rows'):raise ValueError('Scoped partition row-count mismatch')
        matches,safety=sanitize_history_identities(matches)
        report['scoped_history'][str(year)]={'bundle':bundle,'entry':entry,'identity_safety':safety}
        canonical.update({m.match_id:m for m in matches})
    frame['audit_probability']=model.predict_proba(frame)
    rows={'opening':[],'closing':[]};excluded=Counter()
    for row in frame.to_dict('records'):
        match=canonical.get(row['match_id'])
        if match is None:excluded['event_absent_from_slice']+=1;continue
        if not aligned_event(row,match):excluded['event_changed_between_snapshots']+=1;continue
        marker=clean_market_history_marker((match.provider_payload or {}).get('_tbt_market_history'))
        if marker is None:excluded['no_verified_market_marker']+=1;continue
        oriented,_=FeatureBuilder.orient_for_training(match)
        rank_gap=abs(oriented.player1_rank-oriented.player2_rank) if _verified_rank_provenance(match) and oriented.player1_rank is not None and oriented.player2_rank is not None else None
        p=float(row['audit_probability'])
        for kind in rows:
            market=marker.get(kind)
            if not market:continue
            o1,o2,q=align_market(market,oriented.player1_id!=match.player1_id)
            selected_q=q if p>=.5 else 1-q;selected_odds=o1 if p>=.5 else o2
            gap=max(p,1-p)-selected_q
            rows[kind].append({'model':p,'market':q,'target':int(row['target']),'odds1':o1,'odds2':o2,
                'tour':row['tour'],'surface':row['surface'],'level':match.tournament_level or 'unknown',
                'qualifying':'qualifying' if any(s in str(match.round_name or '').lower() for s in ('qualif','qualifying')) else 'other_or_unknown',
                'rank_gap':'unknown' if rank_gap is None else '0_20' if rank_gap<=20 else '21_100' if rank_gap<=100 else '100_plus',
                'favorite':'favorite' if selected_q>=.5 else 'underdog',
                'odds_band':'below_1.5' if selected_odds<1.5 else '1.5_2' if selected_odds<2 else '2_3' if selected_odds<3 else '3_plus',
                'disagreement':'negative' if gap<0 else '0_5pp' if gap<.05 else '5_15pp' if gap<.15 else '15pp_plus',
                'depth':'below_075' if row['data_depth']<.75 else '075_090' if row['data_depth']<.9 else '090_plus'})
    report['exclusions']=dict(excluded)
    report['market_comparison']={kind:{'overall':comparison(values),'segments':{key:grouped(values,key) for key in ('tour','surface','level','qualifying','rank_gap','favorite','odds_band','disagreement','depth')}} for kind,values in rows.items()}
    report['phase']='complete';out.write_text(json.dumps(report,indent=2,allow_nan=False,default=str))
    print(json.dumps({'phase':'complete','test_n':len(frame),'market_n':len(rows['opening']),'excluded':dict(excluded)}),flush=True)


if __name__=='__main__':main()
