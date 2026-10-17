#!/usr/bin/env python3
"""Private-data read-only CDB candidate lookup; metadata matches NEVER authorize import."""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,json,re,unicodedata
from collections import Counter,defaultdict
from pathlib import Path
REQUIRED={'match_id','tour','scheduled_at','player1_id','player2_id','player1_name','player2_name','tournament','round_name'}
ROUNDS={'1/64-finals':'r128','1/32-finals':'r64','1/16-finals':'r32','1/8-finals':'r16','quarter-finals':'qf','semi-finals':'sf','final':'f','r128':'r128','r64':'r64','r32':'r32','r16':'r16','qf':'qf','sf':'sf','f':'f'}
def norm(x):
 s=unicodedata.normalize('NFKD',str(x or '').casefold())
 s=''.join(ch for ch in s if not unicodedata.combining(ch))
 return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]+',' ',s)).strip()
def player_match(src,can):
 a=norm(src).split();b=norm(can).split()
 if len(a)<2 or len(b)<2:return False
 surname=a[:-1]; initial=a[-1][0]; k=len(surname)
 return (b[-k:]==surname and len(b)>k and b[0].startswith(initial)) or (b[:k]==surname and len(b)>k and b[k].startswith(initial))
def round_code(r):
 n=norm(r).replace(' ','')
 aliases={'quarterfinal':'qf','quarterfinals':'qf','semifinal':'sf','semifinals':'sf','final':'f','roundof16':'r16','roundof32':'r32','roundof64':'r64','roundof128':'r128','round1':'r128','round2':'r64','round3':'r32','round4':'r16'}
 return ROUNDS.get(str(r).lower(),aliases.get(n,n))
def tournament_match(src,can):
 a,b=norm(src),norm(can)
 for v in ('atp','wta','indoor','singles','men','open','masters','1000'):
  a=re.sub(r'\b'+v+r'\b','',a).strip();b=re.sub(r'\b'+v+r'\b','',b).strip()
 a=' '.join(a.split()).replace('french','roland garros')
 b=' '.join(b.split()).replace('french','roland garros')
 return bool(a and b and (a==b or re.search(r'\b'+re.escape(a)+r'\b',b) or re.search(r'\b'+re.escape(b)+r'\b',a)))
def to_date(v):
 if isinstance(v,dt.date):return v.date() if isinstance(v,dt.datetime) else v
 return dt.datetime.fromisoformat(str(v).replace('Z','+00:00')).date()
def score_games(s):
 vals=re.findall(r'(?<!\d)(\d)[-:](\d)(?!\d)',str(s or ''))
 return tuple((int(a),int(b)) for a,b in vals) if 2<=len(vals)<=5 else None
def score_compatible(src,cdb,swapped):
 a,b=score_games(src),score_games(cdb)
 if a is None or b is None:return None
 if swapped:b=tuple((q,p) for p,q in b)
 return a==b
def candidates(source,canons):
 out=[]
 for c in canons:
  if norm(c.get('tour'))!=norm(source['tour']):continue
  if abs((to_date(c['scheduled_at'])-to_date(source['date_utc'])).days)>2:continue
  if not tournament_match(source['tournament'],c['tournament']):continue
  if round_code(source['round'])!=round_code(c['round_name']):continue
  direct=player_match(source['home_player'],c['player1_name']) and player_match(source['away_player'],c['player2_name'])
  swapped=player_match(source['home_player'],c['player2_name']) and player_match(source['away_player'],c['player1_name'])
  if direct==swapped:continue
  if not c.get('match_id') or not c.get('player1_id') or not c.get('player2_id') or c['player1_id']==c['player2_id']:continue
  sc=score_compatible(source['set_games_home_away'],c.get('score') or c.get('result') or '',swapped)
  if sc is False:continue
  h=c['player2_id'] if swapped else c['player1_id'];a=c['player1_id'] if swapped else c['player2_id']
  out.append({'canonical_match_id':str(c['match_id']),'canonical_home_player_id':str(h),'canonical_away_player_id':str(a),'orientation':'reversed' if swapped else 'same','score_checked':sc is True,'score_unavailable':sc is None,'source_native_ids_identical':str(source['home_native_id'])==str(h) and str(source['away_native_id'])==str(a)})
 return out
def verify_files(folder,release):
 assets={a['name']:a for a in release['assets']}
 mfile=folder/'history_manifest.json';digest=hashlib.sha256(mfile.read_bytes()).hexdigest()
 if assets['history_manifest.json'].get('digest')!='sha256:'+digest:raise ValueError('manifest SHA mismatch')
 m=json.loads(mfile.read_text())
 for y in range(2021,2026):
  n=f'history-{y}.parquet';p=folder/n;d=hashlib.sha256(p.read_bytes()).hexdigest()
  if assets[n].get('digest')!='sha256:'+d or m['years'][str(y)]['sha256']!=d or m['years'][str(y)]['bytes']!=p.stat().st_size:raise ValueError('CDB partition SHA/manifest mismatch '+n)
def scan(folder,source_file,release):
 import pyarrow.parquet as pq
 verify_files(folder,release)
 with source_file.open(newline='',encoding='utf8') as f:sources=list(csv.DictReader(f,delimiter='|'))
 if len(sources)!=26 or len({r['source_event_id'] for r in sources})!=26:raise ValueError('invalid 26-source ledger')
 canons={}
 for year in range(2021,2026):
  pf=pq.ParquetFile(folder/f'history-{year}.parquet');cols=set(pf.schema_arrow.names)
  if not REQUIRED.issubset(cols):raise ValueError('CDB schema missing '+','.join(sorted(REQUIRED-cols)))
  canons[year]=pf.read(columns=sorted(REQUIRED|({'score','result'}&cols))).to_pylist()
 results=[];owners=defaultdict(set)
 for s in sources:
  refs=candidates(s,canons[to_date(s['date_utc']).year])
  for x in refs:owners[x['canonical_match_id']].add(s['source_event_id'])
  results.append({'source_event_id':s['source_event_id'],'source_home_native_id':s['home_native_id'],'source_away_native_id':s['away_native_id'],'status':'NO_CONTEXT_MATCH' if not refs else 'CONTEXT_AMBIGUOUS' if len(refs)>1 else 'UNIQUE_CONTEXT_CANDIDATE_NOT_ID_VERIFIED','proposals':refs,'independent_provider_event_proof':False,'write_authorized':False})
 for r in results:
  if any(len(owners[x['canonical_match_id']])>1 for x in r['proposals']):r['status']='CDB_TARGET_COLLISION_REVIEW'
 return {'schema':'BLINQ_26_LIVE_CDB_CONTEXT_ONLY_V1','source_count':26,'counts':dict(Counter(x['status'] for x in results)),'verified_provider_identity':0,'cdb_writes':0,'bulk_import_authorized':False,'rows':results}
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for n in ('cdb-dir','source','release-json','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();result=scan(a.cdb_dir,a.source,json.loads(a.release_json.read_text()))
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
 print('CDB26_READONLY',result['source_count'],result['counts'],'verified_provider_identity=0','cdb_writes=0')
