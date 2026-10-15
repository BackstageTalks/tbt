"""Stage only missing CDB serve/return fields on independently proven FIX4 matches.

Read-only, immutable source/CDB SHA-pinned, never publishes canonical partitions.
Generates stage for governed NULL-only importer; existing stat conflicts quarantine.
"""
from __future__ import annotations
import argparse,collections,gzip,hashlib,json,math,zipfile
from pathlib import Path
if __package__:
 from .fix4_strict_cdb_crosswalk import (STAGE_SHA,sha,source_rows,canonical_index,
                                        canonical_ids,match_one,obj)
else:
 from fix4_strict_cdb_crosswalk import (STAGE_SHA,sha,source_rows,canonical_index,
                                        canonical_ids,match_one,obj)

STATS_INDICES={'aces':7,'double_faults':8}
RATES={'first_serve_win':(11,12),'second_serve_win':(13,14),
       'service_points_won':(26,27),'return_points_won':(28,29),
       'break_point_serve_win':(15,16),'break_point_return_win':(23,24)}

def side(data,offset=0):
 out={}
 for key,i in STATS_INDICES.items():
  try:v=float(data[i+offset])
  except (ValueError,TypeError,IndexError):continue
  if not math.isfinite(v) or not v.is_integer() or v<0 or v>200:continue
  out[key]=float(v)
 for key,(nidx,didx) in RATES.items():
  try:n=float(data[nidx+offset]);d=float(data[didx+offset])
  except (ValueError,TypeError,IndexError):continue
  if all(math.isfinite(x) for x in (n,d)) and 0<=n<=d and d>0 and n.is_integer() and d.is_integer():
   out[key]=n/d
 return out

def incoming_stats(raw,win_is_p1):
 if len(raw)!=59:raise ValueError('SOURCE_STAT_WRONG_WIDTH')
 winner=side(raw);loser=side(raw,27) # loser indices start at 34, winner at 7: delta=27
 out={}
 for prefix,s in (('p1',winner),('p2',loser)) if win_is_p1 else (('p2',winner),('p1',loser)):
  out.update({f'{prefix}_{key}':val for key,val in s.items()})
 return out

def signature(row):
 return {'tour':str(row['tour']).lower(),
   'scheduled_date_utc':row['scheduled_at'].date().isoformat() if hasattr(row['scheduled_at'],'date') else str(row['scheduled_at'])[:10],
   'player1_id':str(row['player1_id']),'player1_name':str(row['player1_name']),
   'player2_id':str(row['player2_id']),'player2_name':str(row['player2_name']),
   'surface':str(row['surface'] or ''),'tournament':str(row['tournament'] or ''),
   'round_name':str(row['round_name'] or ''),'winner_id':str(row['winner_id'] or '')}

def candidate_delta(incoming,existing):
 add={};conf=[];identical=0
 for key,v in incoming.items():
  old=existing.get(key)
  if old is None:
   add[key]=v;continue
  try:x=float(old)
  except (ValueError,TypeError):conf.append(key);continue
  tolerance=0 if key.endswith(('aces','double_faults')) else 0.01
  if not math.isfinite(x) or abs(x-v)>tolerance:conf.append(key)
  else:identical+=1
 return add,conf,identical

def stage(stage_zip,bridge,private_links,private_players,official_players,cdb,out,strict_expected=None):
 if sha(stage_zip)!=STAGE_SHA:raise ValueError('SOURCE_STAGE_HASH_DRIFT')
 sources,_=source_rows(stage_zip,bridge)
 def gzrows(p):
  with gzip.open(p,'rt') as f:
   for line in f:
    if line.strip():yield json.loads(line)
 links=list(gzrows(private_links));discover=list(gzrows(private_players))
 if strict_expected is not None and len(links)!=strict_expected:raise ValueError('WITNESS_COUNT_DRIFT')
 ids,conflicts=canonical_ids(json.loads(x) for x in Path(official_players).read_text().splitlines())
 for row in discover:
  c=row['source_atp_id'];target=row['canonical_player_id']
  if row.get('write_authorized') is not False or row.get('distinct_tournaments',0)<2 or c in ids or target in ids.values():
   raise ValueError('NONINDEPENDENT_DISCOVERED_PLAYER_ID')
  ids[c]=target
 idx,count,manifest_sha=canonical_index(cdb)
 unique={(row['source_match_id'],row['canonical_match_id']) for row in links}
 if len(unique)!=len(links):raise ValueError('DUPLICATE_CANONICAL_LINK')
 source_ids={a for a,b in unique}
 stats={};matched_source=0
 with zipfile.ZipFile(stage_zip) as z:
  with z.open('atp_archive_stats.jsonl.gz') as raw,gzip.open(raw,'rt') as stream:
   for line in stream:
    row=json.loads(line);mid=str(row['source_stat_id']).lower()
    if mid not in source_ids:continue
    if mid in stats:raise ValueError('NONUNIQUE_SOURCE_STAT')
    stats[mid]=row['data']
 pending=[];counts=collections.Counter();conflicts_review=[]
 for proof in links:
  mid=proof['source_match_id'];src=sources.get(mid)
  if not src or src['source_native_key']!=proof['source_native_key']:
   raise ValueError('OFFICIAL_SOURCE_LINK_MISMATCH')
  win,lose=ids.get(src['winner_atp_id']),ids.get(src['loser_atp_id'])
  if not win or not lose or win==lose:raise ValueError('DROPPED_PLAYER_EVIDENCE')
  src=dict(src,winner_cdb_id=win,loser_cdb_id=lose)
  possible=idx.get((src['year'],frozenset([win,lose])),[])
  chosen,_,status=match_one(src,possible)
  if status!='unique_full_proof' or chosen is None or str(chosen[0]['match_id'])!=str(proof['canonical_match_id']):
   raise ValueError('STALE_ATP_CDB_EVENT_EVIDENCE')
  cdbrow,oldstats=chosen
  raw=stats.get(mid)
  if not raw:
   counts['missing_source_stats']+=1;continue
  if str(raw[0]).lower()!=mid:raise ValueError('STATS_SOURCE_MATCH_ID_MISMATCH')
  observed=incoming_stats(raw,str(cdbrow['player1_id'])==win)
  counts['source_stat_values']+=len(observed)
  if len(observed)<8:counts['undercomplete_source']+=1;continue
  new,conf,matching=candidate_delta(observed,oldstats)
  counts['matching_existing_fields']+=matching
  if conf:
   counts['source_stat_conflicts']+=1;counts['conflicting_cells']+=len(conf)
   conflicts_review.append({'canonical_match_id':str(cdbrow['match_id']),'keys':sorted(conf)})
   continue
  if not new:
   counts['already_complete']+=1;continue
  pending.append({'schema':1,'match_id':str(cdbrow['match_id']),
   'canonical':signature(cdbrow),'incoming_stats':new,
   'provenance':[{'source':'blinq_fix4_atptour_strict_official_score',
     'source_match_id':mid,'native_event':src['source_native_key'],
     'proof':'independent_both_player_ids_plus_full_set_tape',
     'source_stage_sha256':STAGE_SHA,'source_row_scope':'post_match'}],
   'import_ready':True,'canonical_existing_stats_sha256':hashlib.sha256(json.dumps(oldstats,sort_keys=True).encode()).hexdigest()})
  counts['candidate_matches']+=1;counts['candidate_null_cells']+=len(new)
  for k in new:counts['null_'+k]+=1
 pending.sort(key=lambda x:x['match_id']);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 if len({x['match_id'] for x in pending})!=len(pending):raise ValueError('DUPLICATE_NULL_TARGET')
 path=out/'protected-null-only-stage.jsonl'
 with path.open('w') as f:
  for row in pending:f.write(json.dumps(row,sort_keys=True)+'\n')
 result={'schema':'FIX4_STRICT_NULL_ONLY_CDB_PREFLIGHT_V1',
    'read_only':True,'production_writes':0,'training_allowed':False,
    'cdb_manifest_sha256':manifest_sha,'source_sha256':STAGE_SHA,
    'identity_links_sha256':sha(private_links),'observed_identity_links':len(links),
    'new_player_ids':len(discover),'counts':dict(counts),
    'private_stage_sha256':sha(path),'review_count':len(conflicts_review),
    'note':'Staged candidates are NOT published. Apply only under global lock + backup + CAS + full persisted readback.'}
 (out/'report.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 with (out/'conflict_review_private.jsonl').open('w') as f:
  for row in conflicts_review:f.write(json.dumps(row,sort_keys=True)+'\n')
 return result

def main():
 p=argparse.ArgumentParser()
 for arg in ('stage','bridge','private-links','private-players','official-players','cdb','out'):p.add_argument('--'+arg,required=True,type=Path)
 a=p.parse_args();r=stage(a.stage,a.bridge,a.private_links,a.private_players,a.official_players,a.cdb,a.out)
 print('FIX4_CURRENT_CDB_NULL_DELTA',json.dumps({'links':r['observed_identity_links'],'counts':r['counts'],'production_writes':0}))
if __name__=='__main__':main()