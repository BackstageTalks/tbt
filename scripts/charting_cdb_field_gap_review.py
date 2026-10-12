#!/usr/bin/env python3
"""Fail-closed, READ-ONLY charting x canonical CDB match-level stat/gap review.

Does not attest event identity, approve import, or modify a canonical release.
Only compare already unique compound-metadata candidates. Source player profiles
are derived from the same archive and MUST NOT be counted as independent proof.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

MAX_PROFILE_RAW_BYTES = 8_000_000
FIELDS = ("aces", "double_faults", "first_serve_win", "second_serve_win",
          "service_points_won", "return_points_won", "break_point_serve_win")

def sha(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for c in iter(lambda:f.read(1 << 20),b''): h.update(c)
    return h.hexdigest()

def read_json(path):
    with (gzip.open(path,'rt',encoding='utf-8') if str(path).endswith('.gz') else path.open(encoding='utf-8')) as stream:
        return json.load(stream)

def rows(path):
    with (gzip.open(path,'rt',encoding='utf-8') if str(path).endswith('.gz') else path.open(encoding='utf-8')) as stream:
        for s in stream:
            if s.strip(): yield json.loads(s)

def canonical_rows(path):
    if str(path).endswith('.parquet'):
        import pyarrow.parquet as pq
        pf=pq.ParquetFile(path)
        needed={'match_id','player1_id','player2_id','player1_name','player2_name','stats_json','tour',
                'scheduled_at','tournament','surface','round_name','winner_id','provider_context_json'}
        columns=sorted(needed & set(pf.schema.names))
        if not {'match_id','player1_id','player2_id','stats_json'}.issubset(columns):
            raise ValueError('Missing required canonical columns '+path.name)
        for batch in pf.iter_batches(columns=columns,batch_size=16_384):
            yield from batch.to_pylist()
    else:
        yield from rows(path)

def finite_nonnegative_int(x):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):return None
    if x<0 or x>100_000 or int(x)!=x:return None
    return int(x)

def stats_observation(obs):
    if not isinstance(obs,dict) or not isinstance(obs.get('stats'),dict):return None,'NO_OBSERVATION'
    s=obs['stats']
    required=('serve_pts','first_in','second_in','first_won','second_won',
              'return_pts','return_pts_won','aces','dfs')
    data={k:finite_nonnegative_int(s.get(k)) for k in required}
    if any(v is None for v in data.values()):return None,'BAD_OR_MISSING_POINT_COUNTS'
    d=data
    if not (0<d['serve_pts']<=2000 and 0<d['return_pts']<=2000 and
            d['first_in']+d['second_in']==d['serve_pts'] and
            d['first_won']<=d['first_in'] and d['second_won']<=d['second_in'] and
            d['return_pts_won']<=d['return_pts'] and d['aces']<=d['serve_pts'] and
            d['dfs']<=d['second_in']):
        return None,'INCONSISTENT_COUNTS'
    bp=finite_nonnegative_int(s.get('bk_pts'))
    saved=finite_nonnegative_int(s.get('bp_saved'))
    if (bp is None) != (saved is None) or (bp is not None and (saved>bp or bp>d['serve_pts'])):
        return None,'INCONSISTENT_BREAK_POINTS'
    d.update(bk_pts=bp,bp_saved=saved)
    return d,''

def whole_match(a,b):
    # A charted subset could omit unobserved points. Refuse pretending it covers
    # a full match unless both players' totals agree arithmetically.
    if a['serve_pts']!=b['return_pts'] or b['serve_pts']!=a['return_pts']:
        return False
    if a['return_pts_won']!=b['serve_pts']-b['first_won']-b['second_won']:
        return False
    if b['return_pts_won']!=a['serve_pts']-a['first_won']-a['second_won']:
        return False
    return True

def projection(d,prefix):
    out={prefix+'aces':float(d['aces']),prefix+'double_faults':float(d['dfs']),
         prefix+'service_points_won':(d['first_won']+d['second_won'])/d['serve_pts'],
         prefix+'return_points_won':d['return_pts_won']/d['return_pts']}
    if d['first_in']>0:out[prefix+'first_serve_win']=d['first_won']/d['first_in']
    if d['second_in']>0:out[prefix+'second_serve_win']=d['second_won']/d['second_in']
    if d['bk_pts'] and d['bk_pts']>0:
        out[prefix+'break_point_serve_win']=d['bp_saved']/d['bk_pts']
    return {k:round(v,12) for k,v in out.items()}

def strict_dict(raw):
    if isinstance(raw,dict):return raw
    if isinstance(raw,str):
        d=json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if isinstance(d,dict):return d
    raise ValueError('invalid canonical stats JSON')

def verified_profile(profile_root, relpath, name, tour, source_id):
    relative=Path(relpath)
    if (relative.is_absolute() or '..' in relative.parts or len(relative.parts)!=3 or
        relative.parts[0]!='profiles' or relative.parts[1]!=tour or
        relative.suffix!='.gz'):
        raise ValueError('Unsafe profile path')
    source=(profile_root/relative).resolve()
    if not source.is_relative_to(profile_root.resolve()):raise ValueError('Path escaped profile directory')
    if source.is_symlink() or not source.is_file() or source.stat().st_size>MAX_PROFILE_RAW_BYTES:
        raise ValueError('Missing / too large profile')
    with gzip.open(source,'rb') as f: payload=f.read(MAX_PROFILE_RAW_BYTES+1)
    if len(payload)>MAX_PROFILE_RAW_BYTES:raise ValueError('Profile inflated over cap')
    p=json.loads(payload)
    if p.get('name')!=name or p.get('tour')!=tour or not isinstance(p.get('match_ids'),list):
        raise ValueError('Profile player identity mismatch')
    if not isinstance(p.get('overview_by_match'),list):raise ValueError('Profile observations missing')
    matches=p['match_ids']
    if source_id not in matches:raise ValueError('Match not in profile index')
    observations=[o for o in p['overview_by_match'] if o.get('match_id')==source_id]
    if len(observations)!=1:raise ValueError('Missing/duplicate profile match observation')
    return observations[0], {'profile_sha256':sha(source),'profile_index_id':p.get('player_id')}

def is_present_value(x):
    return x is not None and not (isinstance(x,float) and not math.isfinite(x))

def run(source,players_path,candidates_path,profiles_root,cdb_paths,out,expected_shas=None):
    source,players_path,candidates_path,profiles_root,out=map(Path,(source,players_path,candidates_path,profiles_root,out))
    cdb_paths=list(map(Path,cdb_paths))
    pins=read_json(Path(expected_shas)) if expected_shas else None
    if pins is not None:
        actual={p.name:sha(p) for p in cdb_paths}
        if pins!=actual:raise ValueError('Canonical release SHA/dataset drift; regenerate crosswalk first')
    sources=read_json(source)
    if not isinstance(sources,dict):raise ValueError('Expected original charting ID->metadata mapping')
    players=read_json(players_path)
    if not isinstance(players,list):raise ValueError('Invalid player index')
    owner={};ambiguous=set()
    for r in players:
        if not isinstance(r,dict):continue
        k=(r.get('tour'),r.get('name'))
        if k in owner:ambiguous.add(k)
        owner[k]=r
    candidate_items=list(rows(candidates_path))
    candidate_ids=set();canonical_ids=set();stage=[]
    for item in candidate_items:
        if item.get('status') not in {'CANDIDATE_COMPOUND_ONLY','RESEARCH_TOURNAMENT_ALIAS_ONLY','RESEARCH_ONE_DAY_UTC_SHIFT_ONLY'}:continue
        sid=item.get('source_match_id');mid=item.get('canonical_match_id_candidate')
        if not sid or not mid or sid in candidate_ids or mid in canonical_ids:
            raise ValueError('Duplicate or missing candidate identity')
        candidate_ids.add(sid);canonical_ids.add(mid)
        stage.append(item)
    current={}; all_ids=set(); rows_checked=0
    for path in cdb_paths:
        for r in canonical_rows(path):
            rows_checked+=1
            mid=str(r.get('match_id') or '')
            if not mid or mid in all_ids:raise ValueError('Duplicate/empty canonical match ID')
            all_ids.add(mid)
            if mid in canonical_ids:current[mid]=r
    counts=Counter(cdb_rows_scanned=rows_checked,source_match_rows=len(sources),
                   compound_candidate_rows=sum(x['status']=='CANDIDATE_COMPOUND_ONLY' for x in stage),
                   context_review_candidate_rows=sum(x['status']!='CANDIDATE_COMPOUND_ONLY' for x in stage))
    outcomes=[]
    for x in stage:
        source_id=x['source_match_id'];canonical_id=x['canonical_match_id_candidate']
        row={'source_match_id':source_id,'source_match_status':x['status'],
             'canonical_match_id_candidate':canonical_id,
             'status':'','missing_cells':{},'matching_existing_cells':[],
             'conflicting_existing_cells':[],'write_authorized':False,
             'identity_evidence':'compound_metadata_only_not_independently_attested'}
        try:
            info=sources[source_id];c=current[canonical_id]
            assert isinstance(info,dict)
            tour=info['tour'];names=info['players'];sides=x['source_side_to_canonical_side']
            if (tour not in ('atp','wta') or len(names)!=2 or
                sides not in ([1,2],[2,1]) or
                [str(c['player1_id']),str(c['player2_id'])]!=x['canonical_player_ids_candidate']):
                raise ValueError('Identity mismatch with current CDB')
            if (names[0]==names[1] or
                any((tour,n) in ambiguous or (tour,n) not in owner for n in names)):
                raise ValueError('Ambiguous/missing source profile')
            raw=[];proof=[]
            for name in names:
                record=owner[(tour,name)]
                obs,p=verified_profile(profiles_root,record['path'],name,tour,source_id)
                if str(obs.get('date')) != str(info.get('date')) or str(obs.get('surface'))!=str(info.get('surface')):
                    raise ValueError('Profile event context mismatch')
                d,error=stats_observation(obs)
                if error:raise ValueError(error)
                raw.append(d);proof.append(p)
            if not whole_match(raw[0],raw[1]):raise ValueError('Point totals differ across opponents')
            projected={}
            for i,d in enumerate(raw):
                prefix='p1_' if sides[i]==1 else 'p2_'
                projected.update(projection(d,prefix))
            existing=strict_dict(c['stats_json'])
            row['source_profile_provenance']=proof
            row['candidate_fields']=len(projected)
            for field,value in sorted(projected.items()):
                previous=existing.get(field)
                if not is_present_value(previous):
                    # Malformed non-null values are not legal NULLs.
                    if previous is not None:raise ValueError('Invalid non-null canonical stats')
                    row['missing_cells'][field]=value
                elif isinstance(previous,bool) or not isinstance(previous,(int,float)):
                    raise ValueError('Non-numeric canonical stats '+field)
                elif abs(float(previous)-value) <= (0 if field.endswith(('aces','double_faults')) else 1e-6):
                    row['matching_existing_cells'].append(field)
                else:
                    row['conflicting_existing_cells'].append(field)
            # Existing provider metrics that disagree must prevent promotion of
            # the entire source match, not silently select the convenient cells.
            if row['conflicting_existing_cells']:
                row['status']='QUARANTINE_EXISTING_STATS_CONFLICT'
                row['missing_cells']={}
            elif row['missing_cells']:
                row['status']='RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF'
            else:
                row['status']='NO_CANONICAL_FIELD_GAP'
        except (KeyError,ValueError,TypeError,AssertionError,IndexError,FileNotFoundError) as exc:
            row['status']='QUARANTINE_SOURCE_OR_CDB_INCONSISTENT'
            row['reason']=str(exc)[:180]
            row['missing_cells']={}
        counts[row['status']]+=1
        counts['matching_canonical_cells']+=len(row['matching_existing_cells'])
        counts['conflicting_canonical_cells']+=len(row['conflicting_existing_cells'])
        if row['status']=='RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF':
            counts['missing_candidate_cells_not_approved']+=len(row['missing_cells'])
        outcomes.append(row)
    assert len(outcomes)==len(stage)
    out.mkdir(parents=True,exist_ok=True)
    output=out/'field_gap_research_only.jsonl.gz'
    with gzip.open(output,'wt',encoding='utf-8') as f:
        for r in outcomes:f.write(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    manifest={'schema':1,'mode':'READ_ONLY_NO_CANONICAL_WRITES',
              'charting_source_sha256':sha(source),'charting_index_sha256':sha(players_path),
              'crosswalk_sha256':sha(candidates_path),
              'canonical_partition_sha256':{p.name:sha(p) for p in cdb_paths},
              'counts':dict(sorted(counts.items())),
              'field_gap_output_sha256':sha(output),
              'independent_event_and_both_player_id_proof':False,
              'approved_cdb_cells':0,'canonical_cdb_writes':0,'production_mutated':False,
              'next_gate':'independent event+participant reference; exact current NULL-only CAS; global writer lock; immutable prewrite backup; remote readback'}
    (out/'field_gap_report.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    return manifest

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--charting',required=True,type=Path)
    a.add_argument('--players',required=True,type=Path)
    a.add_argument('--crosswalk',required=True,type=Path)
    a.add_argument('--profiles-root',required=True,type=Path)
    a.add_argument('--cdb',required=True,type=Path,nargs='+')
    a.add_argument('--expected-shas',type=Path)
    a.add_argument('--output',required=True,type=Path)
    x=a.parse_args()
    print(json.dumps(run(x.charting,x.players,x.crosswalk,x.profiles_root,x.cdb,x.output,x.expected_shas),indent=2))
if __name__=='__main__':main()