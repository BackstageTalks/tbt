#!/usr/bin/env python3
"""Fail-closed source-to-CDB exact NULL audit for 2022-25 ATP/WTA season CSVs.

READ ONLY; never publishes canonical Parquet or grants underlying source rights.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

SOURCE_SHA = {
 '2022-atp-season.csv':'820d9723863cff2df65b8bbace4e0f9f42591c2f371fb8af526ce1d9efd547f8',
 '2022-wta-season.csv':'6638fbc41a8e5ed275f17cff03acc3a6df85399ba99e12be73fc89cc23185e81',
 '2023-atp-season.csv':'bba6a2a2c2a9a6d6e0a7a6655fe09bdda1915cb60def7fc4253a12e559c1eece',
 '2023-wta-season.csv':'6025591c5c1a5a1fbbfa0b9bbbf3bf4cb5d7e86a8da47c115c0a795b866c4859',
 '2024-atp-season.csv':'d2bafc5d528029b8e207e63e2ccf9421525fc0bda1489ef3a8a0a6acf86291ab',
 '2024-wta-season.csv':'70f5b7e26c0ff5d88d1492bdbaa1ae5c362bf0ff91d7b14f1f8a9e1adc3b198a',
 '2025-atp-season.csv':'de4c7466a2425d85e62e454ae9a0ccc084eb9b02a234ba5b729e675c30a7c1f6',
 '2025-wta-season.csv':'bfccceaa8d8e17f1656d6009f02f58199b0be061898495ecd36ab35f670f194d',
}
REQUIRED_YEARS = tuple(range(2021, 2026))
FIELDS = ('aces', 'double_faults')
RAW_FIELDS = ('home_aces','away_aces','home_double_faults','away_double_faults')

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def load_dict(value):
    if isinstance(value,dict): return value
    if isinstance(value,str):
        x=json.loads(value, parse_constant=lambda p: (_ for _ in ()).throw(ValueError(p)))
        if isinstance(x,dict):return x
    raise ValueError('Invalid JSON object')

def provider_event_id(ctx):
    vals=[]
    for key in ('_tbt_provider_event_id','provider_event_id','event_id','eventId','id'):
        x=ctx.get(key)
        if x not in (None,''):vals.append(str(x))
    for nested,key in (('event','id'),('_tbt_event_identity','event_id'),('_tbt_statistics','event_id')):
        section=ctx.get(nested)
        if isinstance(section,dict) and section.get(key) not in (None,''):vals.append(str(section[key]))
    return vals[0] if vals and len(set(vals))==1 else None

def p_id(value):
    if isinstance(value,dict):value=value.get('id')
    return str(value).strip() if value not in (None,'') else ''

def source_player_sides(ctx,expected_event):
    identity=ctx.get('_tbt_event_identity')
    if not isinstance(identity,dict) or str(identity.get('event_id'))!=expected_event:return None
    sides=(p_id(ctx.get('homeTeam')),p_id(ctx.get('awayTeam')))
    if not all(sides):sides=(p_id(identity.get('home')),p_id(identity.get('away')))
    if not all(sides) or sides[0]==sides[1]:return None
    return sides

def utc_start(value):
    import pandas as pd
    ts=pd.Timestamp(value)
    if pd.isna(ts) or ts.tzinfo is None:return None
    return int(ts.timestamp()) if ts.nanosecond==0 and ts.microsecond==0 else None

def count4(row):
    vals=[]
    for k in RAW_FIELDS:
        s=str(row.get(k,'')).strip()
        if not s.isascii() or not s.isdecimal():return None
        v=int(s)
        if not 0<=v<=100:return None
        vals.append(v)
    return dict(zip(RAW_FIELDS,vals))

def source_rows(folder):
    seen=set();source={};counts=Counter()
    for filename,expected in SOURCE_SHA.items():
        path=Path(folder)/filename
        if not path.exists() or sha256(path)!=expected:
            raise ValueError('Source SHA mismatch or missing: '+filename)
        with path.open(newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                counts['source_rows']+=1
                tour={'1':'atp','3':'atp','2':'wta','4':'wta'}.get(str(row.get('tour_type','')))
                evid=str(row.get('match_id','')).strip()
                key=(tour,evid)
                if not evid.isdecimal() or not tour or key in seen:
                    counts['invalid_source_key_or_exhibition']+=1;continue
                seen.add(key);counts['unique_in_scope_source_events']+=1
                if row.get('status')!='FINISHED' or row.get('status_extra')!='FINISHED' or row.get('winner_code') not in ('1','2'):
                    counts['excluded_nonstandard_or_unresolved_result']+=1;continue
                if not str(row.get('home_id','')).isdecimal() or not str(row.get('away_id','')).isdecimal() or row['home_id']==row['away_id']:
                    counts['excluded_missing_stable_source_player_ids']+=1;continue
                try:
                    st=int(row['date_timestamp'])
                    if st<946684800 or st>1924991999:raise ValueError()
                except (ValueError,KeyError,TypeError):
                    counts['excluded_invalid_source_timestamp']+=1;continue
                vals=count4(row)
                if vals is None:
                    counts['excluded_missing_invalid_ace_df']+=1;continue
                counts['eligible_source_count_pairs']+=1
                source[key]={'raw':row,'source_sha':expected,'ts':st,'vals':vals,'src':filename}
    return source,counts

def read_canonical_files(folder,expected):
    import pandas as pd
    allids=set();events=defaultdict(list);counts=Counter()
    for y in REQUIRED_YEARS:
        name=f'history-{y}.parquet';p=Path(folder)/name
        if name not in expected or sha256(p)!=expected[name]:
            raise ValueError('Canonical year SHA mismatch: '+name)
        cols=('match_id','tour','scheduled_at','player1_id','player2_id','winner_id','status','stats_json','provider_context_json')
        frame=pd.read_parquet(p,columns=list(cols))
        counts['current_cdb_rows_examined']+=len(frame)
        for values in frame.itertuples(index=False,name=None):
            row=dict(zip(cols,values));mid=str(row['match_id'])
            if mid in allids:raise ValueError('Duplicate canonical match ID')
            allids.add(mid)
            try:
                ctx=load_dict(row['provider_context_json'])
                eid=provider_event_id(ctx);tour=str(row['tour']).lower()
                if eid and tour in ('atp','wta'):events[(tour,eid)].append((row,ctx))
            except (ValueError,TypeError):
                counts['canonical_invalid_provider_context']+=1
    return events,counts

def analyze(source_folder,history_dir,year_sha,output_dir):
    if set(year_sha)!={f'history-{y}.parquet' for y in REQUIRED_YEARS}:
        raise ValueError('Incomplete year manifest')
    sources,counts=source_rows(source_folder)
    events,extra=read_canonical_files(history_dir,year_sha);counts.update(extra)
    changes=[];per_file=defaultdict(Counter);seen=set()
    for (tour,eid),rec in sources.items():
        raw=rec['raw'];counter=per_file[rec['src']];counter['eligible_source']+=1
        matches=events.get((tour,eid),[])
        if not matches:
            counts['unmatched_provider_event_id']+=1;counter['unmatched']+=1;continue
        if len(matches)!=1:
            counts['ambiguous_provider_event_id']+=1;counter['ambiguous']+=1;continue
        can,ctx=matches[0];mid=str(can['match_id'])
        if mid in seen:
            counts['duplicate_canonical_target']+=1;counter['duplicate_target']+=1;continue
        seen.add(mid)
        if utc_start(can['scheduled_at'])!=rec['ts']:
            counts['different_utc_start']+=1;counter['different_start']+=1;continue
        sides=source_player_sides(ctx,eid)
        if not sides or sides!=(str(raw['home_id']),str(raw['away_id'])):
            counts['missing_or_wrong_independent_home_away_ids']+=1;counter['unverified_sides']+=1;continue
        p1,p2=str(can['player1_id']),str(can['player2_id'])
        if (p1,p2)==sides:home_is_p1=True
        elif (p2,p1)==sides:home_is_p1=False
        else:
            counts['canonical_player_ids_mismatch']+=1;counter['player_mismatch']+=1;continue
        winner=raw['home_id'] if raw['winner_code']=='1' else raw['away_id']
        if str(can['winner_id'])!=str(winner):
            counts['canonical_winner_conflicts']+=1;counter['winner_conflicts']+=1;continue
        if str(can['status']).lower() not in ('finished','completed','ended'):
            counts['canonical_status_not_proven_finished']+=1;counter['status']+=1;continue
        try:existing=load_dict(can['stats_json'])
        except (ValueError,TypeError):
            counts['malformed_cdb_stats_json']+=1;counter['malformed']+=1;continue
        counts['strict_matches_player_event_clock_winner']+=1;counter['strict_matches']+=1
        proposed={};conflicts={};equals=0
        for field in FIELDS:
            for side in ('home','away'):
                target=f'p{1 if (side=="home")==home_is_p1 else 2}_{field}'
                value=rec['vals'][f'{side}_{field}'];old=existing.get(target)
                if old is None:proposed[target]=value
                elif type(old) not in (int,float) or old!=value:conflicts[target]=1
                else:equals+=1
        counts['already_equal_ace_df_cells']+=equals;counter['already_equal_cells']+=equals
        if conflicts:
            counts['conflicting_ace_df_matches']+=1
            counts['conflicting_ace_df_cells']+=len(conflicts)
            counter['conflict_matches']+=1;continue
        if proposed:
            counts['research_only_null_ace_df_cells']+=len(proposed);counter['research_null_cells']+=len(proposed)
            changes.append({'match_id':mid,'event_id':eid,'tour':tour,
              'source_file':rec['src'],'source_sha256':rec['source_sha'],
              'observations':proposed,'write_authorized':False})
        else:
            counts['already_complete_ace_df_matches']+=1;counter['already_complete_matches']+=1
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    (output/'candidate-matches-private.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in changes),encoding='utf-8')
    report={'schema':1,'audit':'exact-original-drive-season-2022-2025-ace-df',
      'source_file_sha256':SOURCE_SHA,'canonical_partition_sha256':year_sha,
      'counts':dict(sorted(counts.items())),
      'by_source':{k:dict(sorted(c.items())) for k,c in sorted(per_file.items())},
      'source_reuse_rights':'UNVERIFIED','writer_executed':False,
      'write_authorized':False,'ready_for_production_write':0,
      'canonical_changed':False,'model_changed':False,
      'same_match_prematch_features_allowed':False,
      'decision':'RESEARCH ONLY; confirm rights, provenance and separate protected CAS writer'}
    (output/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return report

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--source-dir',required=True);a.add_argument('--history-dir',required=True)
    a.add_argument('--year-shas',required=True);a.add_argument('--out',required=True)
    args=a.parse_args()
    report=analyze(args.source_dir,args.history_dir,json.loads(Path(args.year_shas).read_text()),args.out)
    print(json.dumps({'counts':report['counts'],'by_source':report['by_source'],'write_authorized':False},sort_keys=True))

if __name__=='__main__':main()
