#!/usr/bin/env python3
"""One-shot 50 native CDB event ID vs direct Sofascore API metadata, read only.
HTTP 401/403/429 block further requests immediately; no retries or bypass.
"""
import argparse, collections, datetime, hashlib, json, random, time, urllib.request, urllib.error
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for c in iter(lambda:f.read(1048576),b''):h.update(c)
 return h.hexdigest()

def get_object(x):
 if isinstance(x,dict):return x
 try:r=json.loads(x)
 except (ValueError,TypeError):return {}
 return r if isinstance(r,dict) else {}

def pair(ctx):
 p=ctx.get('_tbt_event_identity'); p=p if isinstance(p,dict) else {}
 ids=(str(p.get('home') or ''),str(p.get('away') or ''))
 if not all(s.isdecimal() for s in ids) or ids[0]==ids[1]:return None
 return ids

def candidates(path):
 import pyarrow.parquet as pq
 table=pq.read_table(path,columns=['match_id','tour','scheduled_at','provider_context_json'])
 pools={'atp':[],'wta':[]}
 for r in table.to_pylist():
  tour=str(r['tour']).lower()
  if tour not in pools:continue
  ctx=get_object(r['provider_context_json']); identity=ctx.get('_tbt_event_identity')
  e=str(ctx.get('_tbt_provider_event_id') or '')
  if not e.isdecimal() or not isinstance(identity,dict) or str(identity.get('event_id'))!=e:continue
  par=pair(ctx)
  if par is None:continue
  at=r['scheduled_at'];
  if not isinstance(at,datetime.datetime) or at.tzinfo is None:continue
  pools[tour].append({'tour':tour,'event':e,'home':par[0],'away':par[1],'time':int(at.timestamp()),'cdb_match_id':str(r['match_id'])})
 chosen=[]
 for tour in ('atp','wta'):
  order=sorted(pools[tour],key=lambda r:hashlib.sha256(('BLINQ50-20261014|'+tour+'|'+r['event']).encode()).hexdigest())
  seen=set()
  for row in order:
   if row['event'] not in seen:
    chosen.append(row);seen.add(row['event'])
   if len(seen)==25:break
  if len(seen)!=25:raise ValueError('Not enough distinct '+tour+' source events')
 return chosen

def evaluate(req,src):
 event=src.get('event') if isinstance(src,dict) else None
 if not isinstance(event,dict):return 'NO_EVENT_OBJECT'
 if str(event.get('id') or '')!=req['event']:return 'EVENT_ID_MISMATCH'
 h=event.get('homeTeam');a=event.get('awayTeam')
 if not isinstance(h,dict) or not isinstance(a,dict):return 'MISSING_PARTICIPANTS'
 sides=(str(h.get('id') or ''),str(a.get('id') or ''))
 if sides!=(req['home'],req['away']):return 'PARTICIPANT_ID_MISMATCH'
 if str(event.get('startTimestamp') or '')!=str(req['time']):return 'START_TIMESTAMP_MISMATCH'
 typ=((event.get('status') or {}).get('type') if isinstance(event.get('status'),dict) else None)
 if typ not in ('finished','ended','completed'):return 'NOT_CONFIRMED_FINISHED'
 return 'EXACT_EVENT_BOTH_PLAYERS_START_FINISHED'

def run(p,expected,out):
 if sha(p)!=expected:raise ValueError('Pinned CDB SHA differs: STOP')
 rows=candidates(p);counts=collections.Counter();details=[];stop_reason=None
 for index,row in enumerate(rows):
  url='https://www.sofascore.com/api/v1/event/'+row['event']
  # Basic provenance-identifying user agent; no impersonation, cookies, proxies or bypass.
  req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'BlinQ-identity-research/1.0 (one-shot, no cache bypass)'})
  try:
   with urllib.request.urlopen(req,timeout=12) as response:
    code=response.status
    if code!=200:status='HTTP_'+str(code)
    else:
     body=response.read(512000)
     status=evaluate(row,json.loads(body))
  except urllib.error.HTTPError as ex:
   status='HTTP_'+str(ex.code)
   if ex.code in (401,403,429):stop_reason=status
  except (TimeoutError,urllib.error.URLError,ValueError,UnicodeError,json.JSONDecodeError) as ex:
   status='UNREACHABLE_OR_BAD_RESPONSE'
   stop_reason='NETWORK_OR_PARSE_FAILURE'
  counts[status]+=1
  details.append({'tour':row['tour'],'cdb_event_id':row['event'],'cdb_match_id':row['cdb_match_id'],'status':status,'write_authorized':False})
  if stop_reason:break
  if index < len(rows)-1:time.sleep(.7)
 out.mkdir(parents=True,exist_ok=True)
 (out/'private-sample.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in details))
 summary={'schema':'BLINQ_50_READ_ONLY_SOFASCORE_SAME_NAMESPACE_TEST_V1','requested':50,'planned_atp':25,'planned_wta':25,'actually_queried':len(details),'status_counts':dict(sorted(counts.items())),'early_stop':stop_reason,'confirmed_exact_events_in_checked_sample':counts['EXACT_EVENT_BOTH_PLAYERS_START_FINISHED'],'source_namespace_origin_confirmed':False,'canonical_source_stats_import_authorized':False,'external_reuse_rights_attested':False,'cdb_writes':0,'provider_rapidapi_requests':0,'cdb_parquet_sha256':expected,'private_result_sha256':sha(out/'private-sample.jsonl')}
 (out/'report.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
 print('BLINQ50_AGGREGATES '+json.dumps(summary,sort_keys=True))
 return summary
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--cdb',type=Path,required=True);ap.add_argument('--sha',required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();run(a.cdb,a.sha,a.out)
