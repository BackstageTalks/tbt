#!/usr/bin/env python3
"""2025 CDB provider-identity and NULL-only OPPORTUNITY inventory (READ ONLY).

This proves neither third-party source rights nor source-to-CDB identity. This
script NEVER writes CDB, never imports source stat rows or promotes a model.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, re
from pathlib import Path

FIELDS=("p1_aces","p2_aces","p1_double_faults","p2_double_faults")
URL_ATP=re.compile(r'https?://(?:www\.)?atptour\.com/[^\s"<>]+',re.I)
OFFICIAL_MATCH=re.compile(r'/scores/(?:match-stats/archive|stats-centre/(?:live|archive)|match-stats)/\d{4}/\d+/[a-z0-9_-]+',re.I)
EVENT_KEYS=("_tbt_provider_event_id","provider_event_id","event_id","eventId")


def sha256(path: Path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):
            h.update(chunk)
    return h.hexdigest()


def object_only(s):
    if isinstance(s,dict):return s
    if not isinstance(s,str):return None
    try:
        v=json.loads(s,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError,TypeError):return None
    return v if isinstance(v,dict) else None


def nonempty(x):
    return x is not None and x!=''


def tally(rows):
    count=collections.Counter();seen=set();provider_event_owners=collections.defaultdict(set)
    example_schema={}
    for row in rows:
        count['all_cdb_rows']+=1
        tour=str(row.get('tour') or '').lower()
        if tour not in ('atp','wta'):
            count['non_atp_wta_rows']+=1;continue
        count[f'{tour}_rows']+=1
        mid=str(row.get('match_id') or '')
        if not mid or mid in seen:raise ValueError('Missing or duplicate canonical CDB match ID')
        seen.add(mid)
        ctx=object_only(row.get('provider_context_json'))
        stats=object_only(row.get('stats_json'))
        if ctx is None:
            count['unparseable_provider_context']+=1
        else:
            count['parseable_provider_context']+=1
            for key in EVENT_KEYS:
                if nonempty(ctx.get(key)):count['context_has_'+key]+=1
            identity=ctx.get('_tbt_event_identity')
            if isinstance(identity,dict):
                count['has_tbt_event_identity_dict']+=1
                if nonempty(identity.get('event_id')):count['has_tbt_event_identity_event_id']+=1
                if all(nonempty(identity.get(k)) for k in ('home','away')):
                    count['has_tbt_event_identity_both_participants']+=1
            if nonempty(ctx.get('homeTeam')) and nonempty(ctx.get('awayTeam')):
                count['has_homeTeam_and_awayTeam']+=1
            ids=[(key,str(ctx[key])) for key in EVENT_KEYS if nonempty(ctx.get(key))]
            if len(set(v for k,v in ids))>1:count['conflicting_top_level_event_ids']+=1
            if ids:
                # Source-namespace unknown; repeated numbers are diagnostic only.
                provider_event_owners[(tour,ids[0][1])].add(mid)
            blob=json.dumps(ctx,sort_keys=True,ensure_ascii=False)
            links=URL_ATP.findall(blob)
            if links:count['has_atptour_url_in_context']+=1
            if any(OFFICIAL_MATCH.search(x) for x in links):count['has_explicit_official_atptour_match_link']+=1
            if any('tourney_id' in k.lower() or 'tournament_id' in k.lower() for k in ctx):
                count['has_tournament_id_key']+=1
            if 'match_num' in ctx or 'match_number' in ctx:
                count['has_explicit_match_number_key']+=1
            for key in ctx:
                if key in ('atp_player_id','atp_id','atp_tourney_id','tourney_id','atp_match_id','match_num'):
                    example_schema[key]=example_schema.get(key,0)+1
        if stats is None:
            count['unparseable_stats']+=1;continue
        count['parseable_stats']+=1
        for field in FIELDS:
            # ONLY None is blank. Empty string, false, 0 etc. are NON-NULL.
            if stats.get(field) is None:count['null_'+field]+=1
            else:count['non_null_'+field]+=1
    count['reused_event_ids_within_tour']=sum(len(owners)>1 for owners in provider_event_owners.values())
    return {'schema':'BLINQ_CURRENT_CDB_PROVIDER_IDENTITY_NULL_INVENTORY_2025_V1',
            'scope':'2025 ATP/WTA canonical rows; no third-party ID linking inferred',
            'counts':dict(sorted(count.items())),
            'provider_keys_present':dict(sorted(example_schema.items())),
            'independently_attested_external_source_match_ids':0,
            'independently_attested_external_source_both_player_ids':0,
            'new_cdb_fields_authorized':0,'cdb_writes':0,'no_source_name_or_score_join':True,
            'status':'CURRENT_NULL_AND_IDENTITY_INVENTORY_READ_ONLY__IMPORT_REQUIRES_SOURCE_NAMESPACE_WITNESS'}


def run(path: Path,expected_sha:str):
    if not re.fullmatch(r'[0-9a-f]{64}',expected_sha):raise ValueError('Missing expected SHA')
    actual=sha256(path)
    if actual!=expected_sha:raise ValueError('CDB partition SHA mismatch')
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(path)
    required={'match_id','tour','provider_context_json','stats_json'}
    if not required<=set(pf.schema.names):raise ValueError('Unexpected canonical CDB schema')
    columns=sorted(required)
    def rows():
        for batch in pf.iter_batches(batch_size=1024,columns=columns):
            yield from batch.to_pylist()
    report=tally(rows())
    report['canonical_2025_sha256']=actual
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--history',required=True,type=Path)
    ap.add_argument('--expected-sha256',required=True)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args()
    report=run(args.history,args.expected_sha256)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('BLINQ_CDB_SOURCE_ID_COVERAGE_AGGREGATE '+json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
