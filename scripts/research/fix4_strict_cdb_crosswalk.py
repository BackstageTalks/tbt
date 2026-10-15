"""FIX4 strict ATP score -> CDB evidence-based linkage (read-only).

Only independently verified official ATP player IDs, exact original two-sided
set tape, unique CDB event, tournament/round and tournament time window qualify.
Outputs count aggregates and private source-to-match mapping with NO write rights.
"""
from __future__ import annotations
import argparse,collections,csv,datetime as dt,gzip,hashlib,io,json,re,zipfile
from pathlib import Path

STAGE_SHA='39e62b87455ebd34b9451e5ddf4a752fe30d648f8f3f02603f5e078096bc61ea'
BRIDGE_SHA='da4854ca582a0baae488f9874e608894b8757dcdf72c1379f9a1e2d53c37dff2'
YEARS=(2015,2016,2017,2019)
SET=re.compile(r'^(\d{1,2})(\d{1,2})(?:\((\d{1,2})\))?$')
ROUND={'finals':'f','final':'f','semi finals':'sf','semifinals':'sf','semi final':'sf','quarter finals':'qf','quarterfinals':'qf','round of 16':'r16','round of 32':'r32','round of 64':'r64','round of 128':'r128','round robin':'rr'}

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()

def norm(v):return ' '.join(re.sub(r'[^a-z0-9]+',' ',str(v or '').lower()).split())

def rnd(v):
 s=norm(v)
 return ROUND.get(s,s)

def parse_date(v):
 try:return dt.datetime.strptime(str(v),'%Y.%m.%d').date()
 except (ValueError,TypeError):return None

def tape(s):
 out=[]
 for chunk in str(s or '').strip().split():
  m=SET.fullmatch(chunk)
  if not m:return None
  a,b=int(m[1]),int(m[2]);tb=m[3]
  if a==b or max(a,b)>7 or (tb is not None and (a,b) not in [(7,6),(6,7)]):return None
  if (max(a,b)==6 and abs(a-b)<2) or (max(a,b)==7 and min(a,b) not in (5,6)):
   return None
  if max(a,b)<6:return None
  out.append((a,b))
 return tuple(out) if len(out) in (2,3,4,5) else None

def obj(v):
 if isinstance(v,dict):return v
 if not isinstance(v,str):return {}
 try:r=json.loads(v);return r if isinstance(r,dict) else {}
 except ValueError:return {}

def canonical_tape(stats,winner_p1,nsets):
 if not isinstance(stats,dict):return None
 out=[]
 for n in range(1,nsets+1):
  aa=stats.get('p1_set%d_games'%n);bb=stats.get('p2_set%d_games'%n)
  if isinstance(aa,bool) or isinstance(bb,bool):return None
  try:a,b=int(aa),int(bb)
  except (ValueError,TypeError):return None
  if float(aa)!=a or float(bb)!=b or a<0 or b<0:return None
  out.append((a,b) if winner_p1 else (b,a))
 for n in range(nsets+1,6):
  for prefix in ('p1','p2'):
   if stats.get('%s_set%d_games'%(prefix,n)) not in (None,''):return None
 return tuple(out)

def canonical_ids(crosswalk):
 """Conflicts quarantine BOTH competing owners; never choose first seen."""
 owners=collections.defaultdict(set)
 for row in crosswalk:
  if str(row.get('tour','')).lower()!='atp':continue
  code=str(row.get('atp_tour_id') or '').strip().lower()
  dest=str(row.get('canonical_player_id') or '').strip()
  if not re.fullmatch('[a-z0-9]{2,32}',code) or not dest:continue
  owners[code].add(dest)
 # Enforce one-to-one: same canonical ID may not represent multiple ATP codes.
 inverse=collections.Counter(next(iter(v)) for v in owners.values() if len(v)==1)
 valid={key:next(iter(val)) for key,val in owners.items() if len(val)==1 and inverse[next(iter(val))]==1}
 return valid,len(owners)-len(valid)

def matches_from_zip(z):
 with zipfile.ZipFile(z) as a:
  if a.testzip() is not None:raise ValueError('SOURCE_ZIP_BAD_CRC')
  return list(csv.DictReader(io.StringIO(a.read('atp_archive_hf_strict_source_bridge.csv').decode('utf8'))))

def source_rows(stage_zip, bridge_zip):
 with zipfile.ZipFile(stage_zip) as a:
  if a.testzip() is not None:raise ValueError('STAGE_BAD_CRC')
  official=matches_from_zip(bridge_zip)
  by_id={str(row['atp_score_source_id']).lower():row for row in official}
  if len(by_id)!=len(official):raise ValueError('NONUNIQUE_SOURCE_EVENTS')
  found={}; counters=collections.Counter()
  with a.open('atp_archive_scores.jsonl.gz') as raw,gzip.open(raw,'rt') as f:
   for line in f:
    rec=json.loads(line)
    sourceid=str(rec.get('source_match_id') or '').lower()
    if sourceid not in by_id:continue
    if sourceid in found:raise ValueError('DUPLICATE_SOURCE_SCORE_ROW')
    d=rec['data']
    if len(d)<35:
     counters['bad_score_width']+=1;continue
    start=parse_date(d[5]);end=parse_date(d[9]);t=tape(d[27])
    if not start or not end or not t or end<start or (end-start).days>24:
     counters['invalid_window_or_set_tape']+=1;continue
    b=by_id[sourceid]
    if (str(d[20]).lower()!=str(b['player1_atp_source_id']).lower() or
        str(d[23]).lower()!=str(b['player2_atp_source_id']).lower()):
     counters['source_player_code_conflict']+=1;continue
    if norm(d[19])!=norm(b['winner_name']) or not norm(d[19]):
     counters['source_winner_conflict']+=1;continue
    found[sourceid]={'source_match_id':sourceid,'source_native_key':b['atp_tour_native_key'],
     'year':start.year,'start':start,'end':end,'tape':t,
     'round':rnd(d[16]),'tournament':norm(d[2]),'winner_atp_id':str(d[20]).lower(),
     'loser_atp_id':str(d[23]).lower(), 'winner_name':norm(d[19]), 'loser_name':norm(d[22])}
  counters['source_scores_valid']=len(found)
  counters['source_scores_missing']=len(by_id)-len(found)
  return found,counters

def canonical_index(cdb_dir,years=YEARS):
 import pyarrow.parquet as pq
 base=Path(cdb_dir);man=base/'history_manifest.json';bundle=base/'_tbt_bundle_manifest.json'
 mi=json.loads(man.read_text());bm=json.loads(bundle.read_text());index=collections.defaultdict(list)
 counts=collections.Counter()
 cols=['match_id','tour','scheduled_at','status','player1_id','player2_id','player1_name','player2_name','winner_id','round_name','tournament','stats_json']
 for year in years:
  entry=mi['years'].get(str(year))
  part=base/f'history-{year}.parquet'
  if not entry or sha(part)!=bm['files'].get(part.name,{}).get('sha256'):raise ValueError('CDB_PARTITION_DRIFT:'+str(year))
  for row in pq.read_table(part,columns=cols).to_pylist():
   if str(row['tour']).lower()!='atp':continue
   counts['cdb_atp_scanned']+=1
   p1,p2=str(row['player1_id']),str(row['player2_id'])
   if not p1 or not p2 or p1==p2:counts['bad_cdb_players']+=1;continue
   index[(year,frozenset((p1,p2)))].append(row)
 return index,counts,sha(man)

def match_one(src,possible):
 rejected=collections.Counter();candidates=[]
 for m in possible:
  try:date=m['scheduled_at'].date() if hasattr(m['scheduled_at'],'date') else dt.date.fromisoformat(str(m['scheduled_at'])[:10])
  except ValueError:rejected['bad_cdb_date']+=1;continue
  if not src['start']<=date<=src['end']:rejected['window']+=1;continue
  if rnd(m.get('round_name'))!=src['round']:rejected['round']+=1;continue
  if norm(m.get('tournament'))!=src['tournament']:rejected['tournament']+=1;continue
  if str(m.get('winner_id'))!=str(src['winner_cdb_id']):rejected['winner']+=1;continue
  if str(m.get('status','')).lower() not in ('completed','finished','ended'):rejected['status']+=1;continue
  p1win=str(m['player1_id'])==src['winner_cdb_id']
  st=obj(m.get('stats_json'))
  ct=canonical_tape(st,p1win,len(src['tape']))
  if ct is None:rejected['missing_full_set_tape']+=1;continue
  if ct!=src['tape']:rejected['set_tape_conflict']+=1;continue
  # Source athlete IDs already proved independently by crosswalk and score ordering.
  candidates.append((m,st))
 if len(candidates)!=1:return None,rejected,'ambiguous_target' if len(candidates)>1 else 'no_complete_proof'
 return candidates[0],rejected,'unique_full_proof'


def grow_independent_player_links(sources,canonical,seed,maximum_rounds=8):
 """Iteratively attest ATP player codes with >=2 distinct canonical score events.

 A proposal needs one PREVIOUSLY independent mapped opponent, unique finished
 event with full CDB set tape, exact winner, round, tournament and date window,
 and matching unknown-side *display* name as a veto. Names never grant a link.
 Two proposed events MUST belong to different tournament ids; any competing
 canonical owner or claimed event blocks candidate entirely.
 """
 known=dict(seed);seed_reverse={v for v in known.values()};new=[]
 metrics=collections.Counter()
 by_player=collections.defaultdict(list)
 for (year,pair),rows in canonical.items():
  for pid in pair:by_player[(year,pid)].extend(rows)
 for iteration in range(maximum_rounds):
  proposals=collections.defaultdict(list);target_claims=collections.defaultdict(set)
  for source in sources.values():
   winner_code=source['winner_atp_id'];loser_code=source['loser_atp_id']
   a=known.get(winner_code);b=known.get(loser_code)
   if bool(a)==bool(b):continue
   known_id=a or b;unknown_code=loser_code if a else winner_code
   if known_id is None:continue
   candidates=[]
   for row in by_player.get((source['year'],known_id),()):
    p1,p2=str(row['player1_id']),str(row['player2_id'])
    other=p2 if p1==known_id else p1
    if other in seed_reverse or other in known.values():continue
    inferred=dict(source,winner_cdb_id=a or other)
    single,_,state=match_one(inferred,[row])
    if not single:continue
    # Exact source opponent name is corroboration, never an identifier by itself.
    unknown_name=source['loser_name'] if a else source['winner_name']
    actual_name=norm(row['player2_name'] if p1==known_id else row['player1_name'])
    if not unknown_name or actual_name!=unknown_name:continue
    candidates.append((row,other))
   if len(candidates)!=1:
    if candidates:metrics['ambiguous_partially_matched_event']+=1
    continue
   row,other=candidates[0]
   tournament_key='/'.join(source['source_native_key'].split('/')[:2])
   proof={'atp_id':unknown_code,'canonical_id':other,'source_event':source['source_native_key'],
          'canonical_match_id':str(row['match_id']),'source_tournament':tournament_key,
          'evidence':'trusted_one_player_plus_exact_full_set_and_metadata'}
   proposals[unknown_code].append(proof)
   target_claims[str(row['match_id'])].add(unknown_code)
  verified_now=[]
  all_target_claims={p['canonical_id'] for rows in proposals.values() for p in rows}
  target_owner=collections.defaultdict(set)
  for code,rows in proposals.items():
   for p in rows:target_owner[p['canonical_id']].add(code)
  for code,rows in sorted(proposals.items()):
   canon={p['canonical_id'] for p in rows}
   if len(canon)!=1:
    metrics['player_code_conflicting_canonical_targets']+=1;continue
   dest=next(iter(canon))
   if len(target_owner[dest])!=1 or dest in known.values():
    metrics['canonical_id_competing_owner']+=1;continue
   distinct_events={p['source_event'] for p in rows}
   tournaments={p['source_tournament'] for p in rows}
   if len(distinct_events)<2 or len(tournaments)<2:
    metrics['needs_second_distinct_tournament_proof']+=1;continue
   if any(len(target_claims[p['canonical_match_id']])!=1 for p in rows):
    metrics['shared_canonical_event_claim']+=1;continue
   seen_canonical_events={p['canonical_match_id'] for p in rows}
   if len(seen_canonical_events)!=len(distinct_events):
    metrics['many_source_events_to_one_cdb_event']+=1;continue
   verified_now.append({'source_atp_id':code,'canonical_player_id':dest,'evidence_events':len(distinct_events),
    'distinct_tournaments':len(tournaments),'provenance':rows[:10],
    'status':'EXACT_MULTIEVENT_ATP_CDB_IDENTITY','write_authorized':False})
  if not verified_now:break
  for item in verified_now:
   known[item['source_atp_id']]=item['canonical_player_id'];new.append(item)
  metrics['new_player_ids']+=len(verified_now)
  metrics['rounds_completed']+=1
 return known,new,dict(sorted(metrics.items()))

def audit(stage,bridge,crosswalk_file,cdb,out):
 for p,expected in ((stage,STAGE_SHA),(bridge,BRIDGE_SHA)):
  if sha(p)!=expected:raise ValueError('SOURCE_HASH_MISMATCH:'+str(p))
 sources,c=source_rows(stage,bridge)
 cwpath=Path(crosswalk_file); cw=list(map(json.loads,cwpath.read_text().splitlines()))
 ids,collisions=canonical_ids(cw)
 idx,counts,manifest_sha=canonical_index(cdb)
 counts.update(c); counts['canonical_crosswalk_atp_ids']=len(ids);counts['crosswalk_ambiguous_ids']=collisions
 ids,discovered,expansion=grow_independent_player_links(sources,idx,ids)
 counts['extended_crosswalk_atp_ids']=len(ids)
 counts['new_independent_player_links']=len(discovered)
 verified=[]; review=collections.Counter();match_owners=collections.Counter()
 for source in sources.values():
  a=ids.get(source['winner_atp_id']);b=ids.get(source['loser_atp_id'])
  if not a or not b or a==b:
   review['no_independent_two_player_crosswalk']+=1;continue
  source['winner_cdb_id']=a;source['loser_cdb_id']=b
  candidates=idx.get((source['year'],frozenset((a,b))),())
  if not candidates:review['no_canonical_pair_in_year']+=1;continue
  chosen,reasons,state=match_one(source,candidates)
  if chosen is None:review[state]+=1;review.update({'reject_'+k:v for k,v in reasons.items()});continue
  row,stats=chosen
  match_owners[str(row['match_id'])]+=1
  verified.append({'source_match_id':source['source_match_id'],'source_native_key':source['source_native_key'],
   'canonical_match_id':str(row['match_id']),'canonical_year':source['year'],
   'winner_atp_id':source['winner_atp_id'],'loser_atp_id':source['loser_atp_id'],
   'player_identity_evidence':'independent_atp_id_to_cdb_crosswalk_v1',
   'event_evidence':'unique_tour_round_tournament_window_winner_full_set_tape',
   'write_authorized':False})
 collisions={m for m,n in match_owners.items() if n>1}
 if collisions:
  verified=[x for x in verified if x['canonical_match_id'] not in collisions]
  review['many_to_one_canonical_collision']+=len(collisions)
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 with gzip.open(out/'private_discovered_player_links.jsonl.gz','wt',encoding='utf8') as f:
  for row in discovered:f.write(json.dumps(row,sort_keys=True)+'\n')
 verified.sort(key=lambda x:x['canonical_match_id'])
 private=out/'private_verified_links.jsonl.gz'
 with gzip.open(private,'wt',encoding='utf8') as f:
  for row in verified:f.write(json.dumps(row,sort_keys=True)+'\n')
 report={'schema':'FIX4_CDB_STRICT_TWO_PLAYER_SET_WITNESS_V1','state':'READ_ONLY_IDENTITY_WITNESSES',
  'source_stage_sha256':STAGE_SHA,'source_bridge_sha256':BRIDGE_SHA,
  'trusted_cdb_release_manifest_sha256':manifest_sha,'trusted_crosswalk_sha256':sha(crosswalk_file),
  'counts':dict(sorted(counts.items())),'review':dict(sorted(review.items())),
  'verified_unique_match_links':len(verified),'private_links_sha256':sha(private),'new_player_links_sha256':sha(out/'private_discovered_player_links.jsonl.gz'),
  'crosswalk_expansion':expansion,
  'source_total_strict_triples':15790,'provider_api_calls':0,'cdb_writes':0,'model_changes':0,
  'write_authorized':False,'limitation':'Full-set source and independent canonical player ID witness required. No production import or field NULL audit in this read-only phase.'}
 (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 return report

def main():
 p=argparse.ArgumentParser()
 for arg in ('stage','bridge','crosswalk','cdb','out'):p.add_argument('--'+arg,required=True,type=Path)
 a=p.parse_args();r=audit(a.stage,a.bridge,a.crosswalk,a.cdb,a.out)
 print('FIX4_STRICT_CROSSWALK_RESULT',json.dumps({'counts':r['counts'],'review':r['review'],'verified_unique_match_links':r['verified_unique_match_links'],'cdb_writes':0},sort_keys=True))
if __name__=='__main__':main()