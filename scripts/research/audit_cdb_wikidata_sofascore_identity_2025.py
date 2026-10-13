#!/usr/bin/env python3
"""Fail-closed, READ ONLY research: CDB provider team IDs vs CC0 Wikidata P12302 + P536/P597.

P12302 is a Sofascore ID; TennisApi1/REcodeX upstream namespace equivalence has
not been independently attested. A matching digit here NEVER authorizes
external stats, a canonical player link, an event link, or a CDB write.
"""
from __future__ import annotations
import argparse, collections, gzip, hashlib, json, re, urllib.parse, urllib.request, time
from pathlib import Path

CDB_SHA='3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58'
CC0_SHA='f843cb67d852050580268f42ca207651ff335009a1ecffd50124d578574259a0'
SPARQL='''SELECT ?person ?sofa ?atp ?wta WHERE {
  ?person wdt:P12302 ?sofa .
  { ?person wdt:P536 ?atp } UNION { ?person wdt:P597 ?wta }
} LIMIT 25000'''
QID=re.compile(r'^Q[1-9]\d*$')
NUM=re.compile(r'^\d{2,9}$')
ATP=re.compile(r'^[A-Z][A-Z0-9]{3}$')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def rows_from_cdb(path):
    import pyarrow.parquet as pq
    columns=['tour','provider_context_json']
    pf=pq.ParquetFile(path)
    if not set(columns).issubset(pf.schema.names):raise ValueError('Missing CDB provider identity columns')
    tally=collections.Counter();ids=collections.defaultdict(set)
    for batch in pf.iter_batches(batch_size=1024,columns=columns):
        for item in batch.to_pylist():
            tour=str(item['tour'] or '').lower()
            if tour not in ('atp','wta'):continue
            tally['cdb_matches_'+tour]+=1
            try: ctx=json.loads(item['provider_context_json']) if isinstance(item['provider_context_json'],str) else item['provider_context_json']
            except (ValueError,TypeError):ctx=None
            if not isinstance(ctx,dict):tally['bad_cdb_context']+=1;continue
            e=ctx.get('_tbt_event_identity')
            if not isinstance(e,dict):tally['missing_cdb_provider_participant_identity']+=1;continue
            home,away=str(e.get('home') or ''),str(e.get('away') or '')
            if not NUM.fullmatch(home) or not NUM.fullmatch(away) or home==away:
                tally['bad_cdb_provider_participants']+=1;continue
            ids[tour].update((home,away))
            tally['matches_with_native_participant_pair']+=1
    return ids,tally


def load_pinned_registry(path):
    if sha(path)!=CC0_SHA:raise ValueError('Original CC0 registry SHA changed')
    byqid={}
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:
            if not line.strip():continue
            x=json.loads(line)
            if x.get('license')!='CC0-1.0' or x.get('source')!='Wikidata':raise ValueError('Unlicensed registry')
            q=x.get('wikidata_qid')
            if not isinstance(q,str) or not QID.fullmatch(q) or q in byqid:raise ValueError('Duplicate/bad QID')
            byqid[q]=x
    if len(byqid)<10000:raise ValueError('Pinned registry too small')
    return byqid


def clean_wdqs(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('results'),dict):raise ValueError('Wrong WDQS response')
    records=collections.defaultdict(lambda:collections.defaultdict(set))
    for b in payload['results'].get('bindings',[]):
        if not isinstance(b,dict):raise ValueError('Bad binding')
        get=lambda p:str((b.get(p) or {}).get('value') or '').strip()
        q=get('person').rsplit('/',1)[-1];sofa=get('sofa')
        if not QID.fullmatch(q) or not NUM.fullmatch(sofa):raise ValueError('Bad Wikidata P12302 assertion')
        atp=get('atp').upper();wta=get('wta')
        if atp and not ATP.fullmatch(atp):continue
        if not atp and not wta:continue
        if atp:records[('atp',sofa)][q].add(atp)
        if wta:records[('wta',sofa)][q].add(wta)
    return records


def compare(cdb_ids,pinned,wd_rows):
    counts=collections.Counter()
    review=[]
    for tour in ('atp','wta'):
        counts['unique_cdb_original_participant_ids_'+tour]=len(cdb_ids[tour])
        for native_id in sorted(cdb_ids[tour]):
            candidates=wd_rows.get((tour,native_id),{})
            if not candidates:
                counts[tour+'_not_in_Wikidata_P12302']+=1;continue
            if len(candidates)!=1:
                counts[tour+'_ambiguous_P12302_QIDs']+=1;continue
            q,ext=next(iter(candidates.items()))
            p=pinned.get(q)
            if not p:
                counts[tour+'_qid_not_in_old_CC0_tennis_registry']+=1;continue
            known={str(x).upper() for x in p.get('atp_ids' if tour=='atp' else 'wta_ids',[])}
            if len(known.intersection(ext))!=1:
                counts[tour+'_independent_official_code_mismatch']+=1;continue
            official=next(iter(known.intersection(ext)))
            review.append({'tour':tour,'provider_original_participant_id':native_id,
                           'wikidata_qid':q,'official_player_identifier':official,
                           'evidence':'WDQS_P12302_AND_P536_OR_P597_PLUS_PINNED_CC0_REGISTRY',
                           'source_namespace_verified_by_REcodeX':False,
                           'canonical_player_id':None,'canonical_match_id':None,
                           'write_authorized':False,'source_rights_cleared':False})
            counts[tour+'_distinct_P12302_P536_P597_QID_research_correspondences']+=1
    assert all(row['write_authorized'] is False for row in review)
    return review,dict(sorted(counts.items()))


def query_wdqs():
    base='https://query.wikidata.org/sparql'
    url=base+'?'+urllib.parse.urlencode({'query':SPARQL,'format':'json'})
    req=urllib.request.Request(url,headers={
        'Accept':'application/sparql-results+json',
        'User-Agent':'BlinQ-research-readonly/1.0 (GitHub BackstageTalks/tbt; CC0 authority control)'})
    with urllib.request.urlopen(req,timeout=45) as response:
        if response.status!=200:raise RuntimeError('WDQS HTTP '+str(response.status))
        data=response.read(32*1024*1024+1)
    if len(data)>32*1024*1024:raise ValueError('WDQS payload too large')
    return data,json.loads(data)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--history',type=Path,required=True)
    p.add_argument('--wikidata',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if sha(args.history)!=CDB_SHA:raise ValueError('2025 CDB partition SHA mismatch: STOP')
    ids,counts=rows_from_cdb(args.history)
    pinned=load_pinned_registry(args.wikidata)
    try:data,payload=query_wdqs()
    except Exception as e:raise RuntimeError('WDQS unavailable; STOP without inventing a crosswalk: '+str(e)) from e
    records=clean_wdqs(payload)
    rows,scores=compare(ids,pinned,records)
    args.out.mkdir(parents=True,exist_ok=True)
    detail=args.out/'cdb-sofa-wikidata-private-review.jsonl'
    detail.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows),encoding='utf-8')
    report={'schema':'BLINQ_SOFASCORE_WIKIDATA_P12302_CDB_IDENTITY_RESEARCH_V1',
       'result':'READ_ONLY__DO_NOT_WRITE_CDB',
       'cdb2025_sha256':CDB_SHA,'pinned_tennis_cc0_sha256':CC0_SHA,
       'external_wdqs_payload_sha256':hashlib.sha256(data).hexdigest(),
       'external_query':SPARQL,'cdb_counts':dict(sorted(counts.items())),
       'matching_counts':scores,'candidate_rows':len(rows),'detail_sha256':sha(detail),
       'rights_to_use_sofascore_source_stats_proven':False,
       'recodex_original_participant_namespace_attested':False,
       'canonical_event_ids_proven':0,'cdb_writes':0,
       'same_match_postmatch_features_allowed':False,
       'interpretation':'Matched P12302 Sofascore ID to official ATP P536 or WTA P597 at the same WD QID, only as research. Requires REcodeX event+player native namespace attestation and licensed underlying source before canonical import.'}
    (args.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('BLINQ_CC0_SOFASCORE_P12302_AGGREGATE '+json.dumps(report,sort_keys=True))
if __name__=='__main__':main()
