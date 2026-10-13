#!/usr/bin/env python3
"""BlinQ strictly READ-ONLY, at-most-50 first-party TennisApi event ID challenge.

A matching first-party ID is a consistency test, NEVER an independent Sofascore
bridge, proof of third-party data rights or authorization to write CDB.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request, urllib.error

MAX_EVENTS=50
SHA=re.compile(r'^[a-f0-9]{64}$')
NUM=re.compile(r'^[0-9]+$')
EXPECTED_PROVIDER='https://tennisapi1.p.rapidapi.com'
FIELDS=['match_id','tour','scheduled_at','status','winner_id','player1_id','player2_id','provider_context_json']


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()


def obj(x):
    if isinstance(x,dict):return x
    if isinstance(x,str):
        try:y=json.loads(x,parse_constant=lambda z: (_ for _ in ()).throw(ValueError(z)))
        except (ValueError,TypeError):return None
        return y if isinstance(y,dict) else None
    return None


def canonical_candidate(row):
    tour=str(row.get('tour') or '').lower()
    if tour not in ('atp','wta') or str(row.get('status') or '').lower() not in ('finished','completed','ended'):return None
    ctx=obj(row.get('provider_context_json'))
    if ctx is None:return None
    eid=ctx.get('_tbt_provider_event_id')
    ident=ctx.get('_tbt_event_identity')
    if not NUM.fullmatch(str(eid or '')) or not isinstance(ident,dict) or str(ident.get('event_id'))!=str(eid):return None
    home,away=str(ident.get('home') or ''),str(ident.get('away') or '')
    if not NUM.fullmatch(home) or not NUM.fullmatch(away) or home==away:return None
    if ident.get('status') not in ('finished',None):return None
    names=(str(row.get('player1_id') or ''),str(row.get('player2_id') or ''))
    if not all(NUM.fullmatch(x) for x in names) or len(set(names))!=2:return None
    stamp=row.get('scheduled_at')
    if hasattr(stamp,'timestamp') and getattr(stamp,'tzinfo',None) is not None:
        ts=int(stamp.timestamp())
    else:return None
    if ts<1577836800 or ts>1798761600:return None
    # Explicit aliases MUST not disagree with original event id.
    for k in ('provider_event_id','event_id','eventId'):
        if ctx.get(k) not in (None,'') and str(ctx[k])!=str(eid):return None
    mid=str(row.get('match_id') or '')
    if not mid:return None
    return {'tour':tour,'event_id':str(eid),'home_id':home,'away_id':away,
            'canonical_match_id':mid,'p1_id':names[0],'p2_id':names[1],
            'winner_id':str(row.get('winner_id') or ''),'start_utc':ts}


def select_candidates(rows,per_tour=25):
    found={'atp':{},'wta':{}}
    for row in rows:
        r=canonical_candidate(row)
        if not r:continue
        key=(r['tour'],r['event_id'])
        group=found[r['tour']]
        if r['event_id'] in group:
            # Duplicate source event ID => do not select, mark a collision.
            group[r['event_id']]=None
        else:group[r['event_id']]=r
    result=[]
    for tour in ('atp','wta'):
        values=[r for r in found[tour].values() if r is not None]
        # Recent matches have better odds of still being reachable from provider.
        values.sort(key=lambda r:(-r['start_utc'],hashlib.sha256((tour+'|'+r['event_id']).encode()).hexdigest()))
        if len(values)<per_tour:raise ValueError('Not enough distinct verified native matches for '+tour)
        result.extend(values[:per_tour])
    if len(result)!=2*per_tour or len({(r['tour'],r['event_id']) for r in result})!=len(result):raise ValueError('Invalid deterministic sample')
    return result


def parse_event(payload):
    if not isinstance(payload,dict):return None
    direct=payload.get('event')
    if isinstance(direct,dict):return direct
    data=payload.get('data')
    if isinstance(data,dict):
        if isinstance(data.get('event'),dict):return data['event']
        if isinstance(data.get('id'),(int,str)) and isinstance(data.get('homeTeam'),dict):return data
    if isinstance(payload.get('id'),(int,str)) and isinstance(payload.get('homeTeam'),dict):return payload
    return None


def assess(cdb,api):
    e=parse_event(api)
    if not e:return 'INVALID_OR_EMPTY_API_EVENT'
    if str(e.get('id') or '')!=cdb['event_id']:return 'DIFFERENT_EVENT_ID'
    home=e.get('homeTeam');away=e.get('awayTeam')
    if not isinstance(home,dict) or not isinstance(away,dict):return 'MISSING_API_PARTICIPANTS'
    sides=(str(home.get('id') or ''),str(away.get('id') or ''))
    if sides!=(cdb['home_id'],cdb['away_id']):
        return 'API_REVERSED_PARTICIPANTS' if sides==(cdb['away_id'],cdb['home_id']) else 'DIFFERENT_PARTICIPANT_IDS'
    if str(e.get('startTimestamp') or '')!=str(cdb['start_utc']):return 'DIFFERENT_UTC_START'
    status=e.get('status')
    if not isinstance(status,dict) or status.get('type')!='finished':return 'API_NOT_FINISHED'
    code=e.get('winnerCode')
    if str(code) not in ('1','2'):return 'API_WINNER_UNAVAILABLE'
    winner=sides[int(code)-1]
    if cdb['winner_id']!=winner:return 'DIFFERENT_WINNER_ID'
    return 'SAME_PROVIDER_EVENT_PARTICIPANTS_TIME_WINNER_RECHECK_ONLY'


def response_json(url,headers,body=None,timeout=12):
    req=urllib.request.Request(url,headers=headers,data=body)
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        data=resp.read(2*1024*1024+1)
        if len(data)>2*1024*1024:raise ValueError('Provider response too large')
        return resp.status,resp.headers,json.loads(data)


def probe(sample,budget_url,budget_token,api_key):
    if (len(sample)!=50 or len({(r['tour'],r['event_id']) for r in sample})!=50
        or not budget_url.startswith('https://') or '/api/v1/internal/api-budget/reserve' not in budget_url
        or not budget_token or not api_key):raise ValueError('Incomplete 50-event sample/budget credentials')
    counts=collections.Counter();rows=[];paid=0;reserved=0;consecutive_unavailable=0
    for r in sample:
        # No attempt WITHOUT shared ETag-ledger reservation; no retry; no bypass.
        try:
            status,_,ledger=response_json(budget_url,{'X-Blinq-Worker-Token':budget_token,
                'Content-Type':'application/json'},json.dumps({'purpose':'history','requests':1}).encode(),timeout=9)
            if status!=200 or ledger.get('ok') is not True or not isinstance(ledger.get('budget'),dict):
                counts['BUDGET_UNAVAILABLE_STOP']+=1;break
            b=ledger['budget']
            if b.get('global_limit')!=14550 or b.get('reserved_provider_headroom')!=450:
                counts['BUDGET_CONTRACT_MISMATCH_STOP']+=1;break
            reserved+=1
        except Exception:
            counts['BUDGET_UNAVAILABLE_STOP']+=1;break
        eid=r['event_id'];url=EXPECTED_PROVIDER+'/api/tennis/event/'+eid
        missing_header=False
        try:
            status,header,payload=response_json(url,{'X-RapidAPI-Key':api_key,
                  'X-RapidAPI-Host':'tennisapi1.p.rapidapi.com',
                  'Accept':'application/json'},None,timeout=15)
            paid+=1
            result=assess(r,payload) if status==200 else 'PROVIDER_NOT_200'
            remaining=header.get('x-ratelimit-requests-remaining')
            if remaining is None:
                counts['PROVIDER_RATE_HEADER_MISSING_STOP']+=1
                # We may record this one attempt, but NEVER risk another unmetered billable request.
                missing_header=True
            else:
                missing_header=False
                if not str(remaining).isdigit() or int(remaining)<=450:
                    counts['PROVIDER_HARD_RESERVE_STOP']+=1
                    missing_header=True
        except urllib.error.HTTPError as exc:
            paid+=1
            result='HTTP_'+str(exc.code)
        except Exception as exc:
            paid+=1
            result='UNAVAILABLE_OR_PARSE_FAILURE'
        counts[result]+=1
        rows.append({'tour':r['tour'],'provider_event_id':eid,'canonical_match_id':r['canonical_match_id'],
             'source_native_home_id':r['home_id'],'source_native_away_id':r['away_id'],
             'result':result,'independently_verified_sofascore_ID':False,
             'writes_authorized':False})
        if result in ('HTTP_429','HTTP_401','HTTP_403'):
            counts['PROVIDER_SECURITY_OR_QUOTA_STOP']+=1;break
        if missing_header:break
        consecutive_unavailable=consecutive_unavailable+1 if result in ('HTTP_404','PROVIDER_NOT_200','INVALID_OR_EMPTY_API_EVENT') else 0
        if consecutive_unavailable>=5:
            counts['FIVE_UNAVAILABLE_IN_A_ROW_STOP']+=1
            break
        time.sleep(0.16)
    return counts,rows,reserved,paid


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cdb',required=True,type=Path);p.add_argument('--sha',required=True)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    if not SHA.fullmatch(a.sha) or sha256(a.cdb)!=a.sha:raise ValueError('CDB source not pinned by SHA-256')
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(a.cdb)
    if not set(FIELDS).issubset(pf.schema.names):raise ValueError('CDB schema missing required fields')
    def iter_rows():
        for chunk in pf.iter_batches(batch_size=1024,columns=FIELDS):yield from chunk.to_pylist()
    sample=select_candidates(iter_rows(),25)
    c,r,reserved,paid=probe(sample,os.getenv('BLINQ_SHARED_API_BUDGET_URL',''),
        os.getenv('BLINQ_SHARED_API_BUDGET_TOKEN',''),os.getenv('RAPIDAPI_KEY',''))
    a.out.mkdir(parents=True,exist_ok=True)
    detail=a.out/'api50-match-id-private.jsonl'
    detail.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in r),encoding='utf8')
    report={'schema':'BLINQ_API50_RECODEX_VS_CANONICAL_ID_RECHECK_V1','max_events':50,
      'selected_events':len(sample),'requests_reserved':reserved,'requests_attempted':paid,
      'counts':dict(sorted(c.items())),'verified_sofascore_event_id_equivalences':0,
      'verified_third_party_source_to_cdb_crosswalk':0,
      'claim':'First-party REcodeX event recheck only; NOT independent Sofascore event/participant ID equality',
      'rights_to_fetch_paid_recodeX_api':'existing_subscription',
      'rights_to_reuse_unauthorized_3rd_party_data':False,
      'CDB_writes':0,'model_modified':False,
      'cdb_partition_sha256':a.sha,'detail_sha256':sha256(detail)}
    (a.out/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print('BLINQ_API50_AGGREGATE '+json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
