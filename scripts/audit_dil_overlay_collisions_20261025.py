#!/usr/bin/env python3
"""Aggregate-only read-only collision check for restored DIL; never emits match IDs."""
from __future__ import annotations
import argparse, collections, datetime, hashlib, json, math, sqlite3
from pathlib import Path

def equal(a,b):
    if a==b:return True
    try:return math.isclose(float(a),float(b),rel_tol=1e-8,abs_tol=1e-7)
    except (ValueError,TypeError,OverflowError):return False

def audit(path):
    db=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro&immutable=1',uri=True)
    counts=collections.Counter(); bykey=collections.Counter(); keys_equal=collections.Counter()
    try:
        it=db.execute('SELECT c.stats_json,e.json_metrics FROM dil_enrichment_compact e JOIN canonical_matches c ON c.match_id=e.match_id')
        for cs,es in it:
            counts['overlay_matches_with_canonical_id']+=1
            if counts['overlay_matches_with_canonical_id']%5000==0:
                print('AUDIT_PROGRESS',counts['overlay_matches_with_canonical_id'],flush=True)
            a=json.loads(cs or '{}'); b=json.loads(es or '{}')
            if not isinstance(a,dict) or not isinstance(b,dict):
                counts['invalid_object_rows']+=1;continue
            intersection=set(a)&set(b)
            counts['shared_metric_keys']+=len(intersection)
            collided=False
            for key in intersection:
                if a[key] is None or b[key] is None:
                    counts['null_metric_overlap']+=1
                elif equal(a[key],b[key]):
                    counts['same_value_metric_cells']+=1;keys_equal[str(key)]+=1
                else:
                    counts['conflicting_nonnull_metric_cells']+=1; bykey[str(key)]+=1;collided=True
            if collided:counts['matches_with_collision']+=1
        counts['overlay_total_rows']=db.execute('SELECT COUNT(*) FROM dil_enrichment_compact').fetchone()[0]
        counts['orphan_overlay_rows']=counts['overlay_total_rows']-counts['overlay_matches_with_canonical_id']
        return {'schema':'DIL_REAL_OVERLAY_CANONICAL_COLLISION_AUDIT_V1','status':'PASS' if not counts['conflicting_nonnull_metric_cells'] and not counts['orphan_overlay_rows'] else 'REVIEW_REQUIRED', 'source_kind':'DIL_ONLY_NO_LIVE_CDB', 'counts':dict(counts), 'top_collision_stat_names':bykey.most_common(15), 'source_mutated':False,'production_mutated':False,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    finally: db.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--dil',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();result=audit(a.dil);out=Path(a.report)
    if out.exists():raise FileExistsError('Refuse to overwrite report')
    out.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'counts':result['counts'],'top_collision_stat_names':result['top_collision_stat_names']}))
if __name__=='__main__':main()