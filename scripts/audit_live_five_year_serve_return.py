#!/usr/bin/env python3
"""Strict SHA-pinned, read-only aggregate Serve/Return audit of five real Parquets."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import json,math
from pathlib import Path

YEARS=(2022,2023,2024,2025,2026)
COLS=('match_id','scheduled_at','player1_id','player2_id','winner_id','stats_json')
PAIRS=tuple((f'{p}_{s}',f'{o}_{r}') for p,o in (('p1','p2'),('p2','p1'))
    for s,r in (('first_serve_win','first_return_win'),
                ('second_serve_win','second_return_win'),
                ('service_points_won','return_points_won')))

def digest(path):
    h=sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()

def release_assets(release):
    expected={f'history-{y}.parquet' for y in YEARS}|{'history_manifest.json','_tbt_bundle_manifest.json'}
    found={}
    for row in release.get('assets',[]):
        name=row.get('name')
        if name not in expected:continue
        if name in found or not isinstance(row.get('size'),int):
            raise ValueError('Repeated/invalid canonical asset')
        value=row.get('digest') or ''
        if not value.startswith('sha256:') or len(value)!=71 or any(c not in '0123456789abcdef' for c in value[7:]):
            raise ValueError('Unpinned canonical asset')
        found[name]=(value[7:],row['size'])
    if set(found)!=expected:raise ValueError('Missing canonical asset')
    return found

def valid(v):
    return type(v) in (int,float) and math.isfinite(v) and 0<=v<=1

def analyze(directory,release):
    import pyarrow.parquet as pq
    assets=release_assets(release)
    for name,(sha,size) in assets.items():
        p=directory/name
        if not p.is_file() or p.stat().st_size!=size or digest(p)!=sha:
            raise ValueError('Canonical source digest mismatch: '+name)
    manifest=json.loads((directory/'history_manifest.json').read_text())
    all_count=Counter();per_year={}
    seen=set();now=datetime.now(timezone.utc)
    for year in YEARS:
        counts=Counter();path=directory/f'history-{year}.parquet'
        pf=pq.ParquetFile(path)
        if not set(COLS).issubset(pf.schema_arrow.names):
            raise ValueError('Required canonical schema missing')
        for batch in pf.iter_batches(batch_size=4096,columns=list(COLS)):
            columns=batch.to_pydict()
            for values in zip(*(columns[k] for k in COLS)):
                d=dict(zip(COLS,values));mid=str(d.get('match_id') or '')
                if not mid or mid in seen:raise ValueError('Duplicate/missing canonical match ID')
                seen.add(mid);counts['canonical_matches']+=1
                dt=d['scheduled_at']
                if isinstance(dt,str):dt=datetime.fromisoformat(dt.replace('Z','+00:00'))
                if dt.tzinfo is None or dt.astimezone(timezone.utc).year!=year:
                    raise ValueError('Canonical time/partition mismatch')
                ids=(str(d.get('player1_id') or ''),str(d.get('player2_id') or ''))
                winner=str(d.get('winner_id') or '')
                if not all(ids) or ids[0]==ids[1] or winner not in ids or dt.astimezone(timezone.utc)>=now:
                    counts['noncompleted_or_future']+=1;continue
                raw=d.get('stats_json') or '{}'
                stats=json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite stat'))) if isinstance(raw,str) else raw
                if not isinstance(stats,dict):raise ValueError('Canonical stats must be object')
                new=0;bad=0
                for a,b in PAIRS:
                    x,y=stats.get(a),stats.get(b)
                    if any(v is not None and not valid(v) for v in (x,y)):bad+=1
                    elif x is not None and y is not None:
                        if abs(float(x)+float(y)-1)>1e-6:bad+=1
                    elif (x is None)!=(y is None):new+=1
                if bad:counts['conflicting_pairs']+=bad;counts['matches_with_conflicts']+=1
                if new:counts['staged_matches']+=1;counts['new_stat_values']+=new
        if counts['canonical_matches']!=manifest['years'][str(year)]['rows']:
            raise ValueError('Manifest row count mismatch')
        per_year[str(year)]=dict(counts)
        all_count.update(counts)
    return {'schema':'BLINQ_LIVE_FIVE_YEAR_SERVE_RETURN_NULL_AUDIT_V1',
            'state':'READ_ONLY_CURRENT_SNAPSHOT_NOT_WRITE_AUTHORIZATION',
            'tag':'tbt-data-v1','bundle_manifest_sha256':assets['_tbt_bundle_manifest.json'][0],
            'history_manifest_sha256':assets['history_manifest.json'][0],
            'partition_shas':{str(y):assets[f'history-{y}.parquet'][0] for y in YEARS},
            'counts':dict(all_count),'by_year':per_year,
            'importable_L2_external_source_fields':0,'production_writes':0,
            'new_model_training':False,'required_next':'new live NULL CAS + writer lock + immutable backup/restore + independent remote readback'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--history-dir',type=Path,required=True)
    p.add_argument('--release-json',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    meta=json.loads(args.release_json.read_text())
    if meta.get('tag_name')!='tbt-data-v1':raise ValueError('Wrong canonical tag')
    report=analyze(args.history_dir,meta)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('CANONICAL_FIVE_YEAR_READONLY_AGGREGATE_PASS')

if __name__=='__main__':main()
