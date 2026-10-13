#!/usr/bin/env python3
"""READ-ONLY research: compare exact TennisData.App numeric IDs to TennisApi1 CDB IDs.

Even when ASSUMING TennisApi1 IDs are Sofascore IDs, this never assumes
TennisData.App source IDs are in the same namespace. No name/date/surface
fuzzy matching and NO CDB writes or model modification.
"""
from __future__ import annotations
import argparse, collections, hashlib, json
from pathlib import Path

EXPECTED_LEDGER_SHA='90915bcb5174be1cad2a55ee87ed3dbc998b68b1b6934b4eba849f5aa4a17a00'
EXPECTED_CDB_SHA='3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58'
FIELDS=('p1_aces','p2_aces','p1_double_faults','p2_double_faults')

def sha256(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for ch in iter(lambda:f.read(2**20),b''):h.update(ch)
    return h.hexdigest()

def jsonobj(s):
    if isinstance(s,dict):return s
    if not isinstance(s,str):return None
    try:v=json.loads(s,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
    except (ValueError,TypeError):return None
    return v if isinstance(v,dict) else None

def event(ctx):
    if not isinstance(ctx,dict):return None
    a=[str(ctx[k]) for k in ('_tbt_provider_event_id','provider_event_id','event_id','eventId') if ctx.get(k) not in (None,'')]
    return a[0] if a and len(set(a))==1 else None

def parts(ctx,eid):
    ident=ctx.get('_tbt_event_identity') if isinstance(ctx,dict) else None
    if not isinstance(ident,dict) or str(ident.get('event_id'))!=str(eid):return None
    h,a=str(ident.get('home') or ''),str(ident.get('away') or '')
    if not (h.isascii() and h.isdecimal() and a.isascii() and a.isdecimal() and h!=a):return None
    return (h,a)

def stamp(s):
    import pandas as pd
    try:
        t=pd.Timestamp(s)
        if pd.isna(t) or t.tzinfo is None or t.nanosecond or t.microsecond:return None
        return int(t.timestamp())
    except (ValueError,TypeError,OverflowError):return None

def analyze(source, canonical):
    summary=collections.Counter()
    srci={};cani=collections.defaultdict(list)
    for r in source:
        tour=str(r.get('tour') or '').lower();eid=str(r.get('event_id') or '')
        if tour not in ('atp','wta') or not eid.isascii() or not eid.isdecimal():raise ValueError('Malformed source tour/event ID')
        key=(tour,eid)
        if key in srci:raise ValueError('Duplicate original source event key')
        srci[key]=r;summary['source_total']+=1;summary['source_'+tour]+=1
        summary['source_numeric_id_length_'+str(len(eid))]+=1
    for r in canonical:
        tour=str(r.get('tour') or '').lower()
        if tour not in ('atp','wta'):continue
        ctx=jsonobj(r.get('provider_context_json'));eid=event(ctx)
        summary['cdb_total']+=1;summary['cdb_'+tour]+=1
        if eid and eid.isdecimal():
            cani[(tour,eid)].append((r,ctx))
            summary['cdb_numeric_id_length_'+str(len(eid))]+=1
        else:summary['cdb_provider_event_id_missing_or_not_numeric']+=1
    for key,src in srci.items():
        variants=cani.get(key,[])
        if not variants:continue
        summary['original_source_event_id_equal_to_CDB_provider_ID']+=1
        if len(variants)!=1:summary['duplicate_CDB_provider_ID']+=1;continue
        can,ctx=variants[0];summary['unique_event_id_equal']+=1
        srcpair=(str(src.get('home_id') or ''),str(src.get('away_id') or ''))
        providerpair=parts(ctx,key[1])
        if not providerpair:summary['event_overlap_missing_provider_pair']+=1;continue
        if srcpair not in (providerpair,providerpair[::-1]):summary['same_event_number_but_different_players']+=1;continue
        summary['event_and_both_original_participants_equal']+=1
        try:sts=int(src['ts'])
        except (TypeError,ValueError):continue
        if stamp(can.get('scheduled_at'))!=sts:summary['same_event_players_but_different_UTC_time']+=1;continue
        summary['same_event_players_exact_time']+=1
        if str(can.get('status')).lower() not in ('finished','completed','ended') or src.get('status')!='FINISHED':continue
        winner=srcpair[0] if src.get('winner_code')=='1' else (srcpair[1] if src.get('winner_code')=='2' else '')
        if not winner or str(can.get('winner_id'))!=winner:summary['same_event_players_time_but_winner_unproven']+=1;continue
        summary['all_numeric_event_players_time_winner_match_RESEARCH_ONLY']+=1
        stat=jsonobj(can.get('stats_json'))
        if stat is not None:
            for fld in FIELDS:
                if stat.get(fld) is None:summary['candidate_CDB_NULL_fields_NOT_AUTHORIZED']+=1
    result={'schema':'BLINQ_TENNISDATA_TO_CDB2025_EXACT_NUMERIC_NAMESPACE_HYPOTHESIS_V1',
       'assumption':'TennisApi1 provider namespace equals Sofascore native event/player IDs, UNPROVEN; does not imply TennisData.App uses same IDs',
       'data_scope':'2025 ATP/WTA original season match_id/home_id/away_id compared to current CDB provider IDs',
       'counts':dict(sorted(summary.items())),'source_license_cleared':False,
       'sofascore_equal_to_recodeX_attested':False,
       'direct_source_to_cdb_event_and_players_authoritatively_attested':False,
       'approved_CDB_NULL_fields':0,'CDB_writes':0,'model_modified':False,
       'decision':'NO_PRODUCTION_PROMOTION_FROM_HYPOTHESIS'}
    return result

def run(srcpath:Path,cdbpath:Path):
    if sha256(srcpath)!=EXPECTED_LEDGER_SHA:raise ValueError('private original source ledger SHA mismatch')
    if sha256(cdbpath)!=EXPECTED_CDB_SHA:raise ValueError('current CDB 2025 SHA mismatch')
    import pyarrow.parquet as pq
    cols=['match_id','tour','scheduled_at','player1_id','player2_id','winner_id','status','stats_json','provider_context_json']
    p=pq.ParquetFile(cdbpath)
    if not set(cols)<=set(p.schema.names):raise ValueError('unexpected parquet schema')
    def records():
        for batch in p.iter_batches(batch_size=1024,columns=cols):
            yield from batch.to_pylist()
    return analyze((json.loads(s) for s in srcpath.read_text().splitlines() if s.strip()),records())

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--cdb',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();result=run(a.source,a.cdb);a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('BLINQ_PRIVATE_EVENT_ID_EQUALITY_COUNTS '+json.dumps(result,sort_keys=True))
if __name__=='__main__':main()
