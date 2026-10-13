#!/usr/bin/env python3
"""Read-only current CDB 2025 vs exact user-library Sackmann PbP.zip byte clones.

WARNING: heuristic research matching by names/tournament/score never attests
provider events or source player IDs, licenses, or CDB write authorization.
No existing stats (including zero) can be overwritten by this program.
"""
from __future__ import annotations
import argparse, collections, csv, datetime, hashlib, json, re, unicodedata
from pathlib import Path

ARCHIVE_SHA='6df0fd3f35341dd74c527324b1f9b09b960304c87931cd55185d5918c7bfceea'
MIRROR_COMMIT='83733587353df8a41f2fd4f516147d5aa83f5a8d'
CDB_2025_SHA='3a929b356803af6b0f704d4d3066a053ecf995124ec8f4228487c54c0f534c58'
FILES={
'atp/atp_matches_2025.csv':('atp','ATP_TOUR','78c356ef9328b89ae58a17564d61c02cdad2a3a007f6b8af5cfc17992b11bb2d'),
'atp/atp_matches_futures_2025.csv':('atp','ATP_FUTURES','54dd4611505feccd4976e42564f4d9d0796ebd86f64ad195a3ffc0ae0e9da294'),
'atp/atp_matches_qual_chall_2025.csv':('atp','ATP_QUAL_CHALL','7690c576689d9cafc28d1b9f3293173e87220573db5fd2c47e3097f2ab505ec0'),
'wta/wta_matches_2025.csv':('wta','WTA_TOUR','e4eb002bc6d828b0bd21e04ed286e68722ddc8ccbbb27ea980bf62e938377f96'),
'wta/wta_matches_qual_itf_2025.csv':('wta','WTA_QUAL_ITF','af1b439684a55ae0f7cb42ed5da2b11985f08dac50ac68c06da4faa3ffe19da7')}
FIELDS=('p1_aces','p2_aces','p1_double_faults','p2_double_faults')
SCORE_SET=re.compile(r'^(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?$')

def norm(v):
    s=unicodedata.normalize('NFKD',str(v or '').lower())
    return ' '.join(re.findall(r'[a-z0-9]+',''.join(x for x in s if not unicodedata.combining(x))))

def nround(v):
    s=norm(v);m=re.fullmatch(r'r(?:ound)? (?:of )?(\d+)',s)
    if m:return 'r'+m.group(1)
    if re.fullmatch('r(?:16|32|64|128|256)',s):return s
    if s in ('final','f'):return 'f'
    if s in ('semi final','semifinal','sf'):return 'sf'
    if s in ('quarter final','quarterfinal','qf'):return 'qf'
    if s in ('round robin','rr'):return 'rr'
    if s in ('qualification round 1','qualifying round 1','q1'):return 'q1'
    if s in ('qualification round 2','qualifying round 2','q2'):return 'q2'
    if s in ('qualification round 3','qualifying round 3','q3'):return 'q3'
    return s

def read_sources(folder):
    data=[];c=collections.Counter();index=collections.defaultdict(list)
    for filename,(tour,family,sha) in FILES.items():
        path=folder/filename
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('SOURCE_SHA_MISMATCH:'+filename)
        with path.open(encoding='utf-8-sig',newline='') as f:
            for line_no,row in enumerate(csv.DictReader(f),2):
                c['source_rows']+=1;c['source_'+family]+=1
                if not row['winner_id'] or not row['loser_id'] or row['winner_id']==row['loser_id'] or not row['winner_name'] or not row['loser_name']:
                    c['source_invalid_player_identity']+=1;continue
                try:day=datetime.datetime.strptime(row['tourney_date'],'%Y%m%d').date()
                except (KeyError,ValueError):c['source_bad_tourney_date']+=1;continue
                winner=norm(row['winner_name']);loser=norm(row['loser_name'])
                if not winner or not loser or winner==loser:c['source_name_conflict']+=1;continue
                r={**row,'tour':tour,'family':family,'line':line_no,'date':day,'winner_norm':winner,'loser_norm':loser,
                   'round_norm':nround(row['round']),'tourney_norm':norm(row['tourney_name'])}
                data.append(r)
                index[(tour,frozenset((winner,loser)))].append(r)
                if all(row[x].isascii() and row[x].isdecimal() for x in ('w_ace','l_ace','w_df','l_df')):
                    c['source_complete_ace_df_4']+=1
    if c['source_rows']!=56889:raise ValueError('Unexpected Sackmann 2025 source count')
    return data,index,c

def score_sets(s):
    parts=str(s or '').split();values=[]
    if not 2<=len(parts)<=5:return None
    for p in parts:
        m=SCORE_SET.fullmatch(p)
        if not m:return None
        values.append((int(m.group(1)),int(m.group(2))))
    return values

def stats_obj(raw):
    if isinstance(raw,dict):return raw
    if not isinstance(raw,str):raise ValueError('Stats not JSON object')
    out=json.loads(raw,parse_constant=lambda val: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if not isinstance(out,dict):raise ValueError('Stats not JSON object')
    return out

def source_stats(row,winner_is_p1):
    target={}
    for kind,field in [('ace','aces'),('df','double_faults')]:
        for side in ('w','l'):
            v=row[f'{side}_{kind}']
            if v.isascii() and v.isdecimal() and 0<=int(v)<=100:
                player=1 if ((side=='w')==winner_is_p1) else 2
                target[f'p{player}_{field}']=int(v)
    return target

def full_score_equals(src,canonical_stats,winner_is_p1):
    sets=score_sets(src.get('score'))
    if not sets:return False
    for i,(w,l) in enumerate(sets,1):
        vals=(w,l) if winner_is_p1 else (l,w)
        for side,v in enumerate(vals,1):
            actual=canonical_stats.get(f'p{side}_set{i}_games')
            if type(actual) not in (int,float) or actual!=v:return False
    for i in range(len(sets)+1,6):
        if any(canonical_stats.get(f'p{side}_set{i}_games') is not None for side in (1,2)):
            return False
    return True

def diff_fields(src,canonical_stats,winner_is_p1):
    expected=source_stats(src,winner_is_p1)
    nulls=equals=conflicts=0
    for field,val in expected.items():
        existing=canonical_stats.get(field)
        if existing is None:nulls+=1
        elif type(existing) in (float,int) and existing==val:equals+=1
        else:conflicts+=1
    return nulls,equals,conflicts,len(expected)

def analyze(sources,index,cdb):
    c=collections.Counter();c['source_rows']=len(sources); canonical_candidates=collections.defaultdict(list)
    for values in cdb.itertuples(index=False,name=None):
        row=dict(zip(cdb.columns,values))
        if row['tour'] not in ('atp','wta'):continue
        c['cdb_'+row['tour']+'_rows']+=1
        names=(norm(row['player1_name']),norm(row['player2_name']))
        if not names[0] or not names[1] or names[0]==names[1]:c['cdb_bad_or_same_name']+=1;continue
        winners=str(row['winner_id']); ids=(str(row['player1_id']),str(row['player2_id']))
        if winners not in ids:c['cdb_winner_unassigned']+=1;continue
        winner_is_p1=(winners==ids[0]);wn=names[0] if winner_is_p1 else names[1];ln=names[1] if winner_is_p1 else names[0]
        possibles=index.get((row['tour'],frozenset(names)),[])
        if not possibles:continue
        c['cdb_any_two_exact_names']+=1
        stamp=row['scheduled_at']
        if getattr(stamp,'tzinfo',None) is None:c['cdb_unsafe_naive_timestamp']+=1;continue
        stamp=stamp.date()
        same_winner=[p for p in possibles if p['winner_norm']==wn and p['loser_norm']==ln]
        if not same_winner:c['cdb_names_with_winner_conflict']+=1;continue
        c['cdb_exact_two_names_and_winner']+=1
        dates=[p for p in same_winner if -1<=(stamp-p['date']).days<=24]
        if not dates:c['cdb_no_safe_tourney_date_range']+=1;continue
        c['cdb_names_winner_and_tourney_window']+=1
        tn=norm(row['tournament'])
        same_tourney=[p for p in dates if p['tourney_norm']==tn]
        if not same_tourney:
            c['cdb_tournament_label_differs']+=1;continue
        c['cdb_names_winner_window_tournament_exact']+=1
        round_name=nround(row['round_name'])
        same_round=[p for p in same_tourney if p['round_norm']==round_name]
        if not same_round:
            c['cdb_round_differs']+=1;continue
        c['cdb_names_winner_window_tournament_round_exact']+=1
        if len(same_round)!=1:
            c['cdb_ambiguous_multiple_sackmann_events']+=1;continue
        source=same_round[0]
        try:st=stats_obj(row['stats_json'])
        except (TypeError,ValueError):c['cdb_stats_malformed']+=1;continue
        c['cdb_unique_metadata_research_candidate']+=1
        sc=full_score_equals(source,st,winner_is_p1)
        c['cdb_full_set_score_confirmed' if sc else 'cdb_full_set_score_missing_or_mismatch']+=1
        n,e,conf,k=diff_fields(source,st,winner_is_p1)
        if k!=4:c['cdb_source_not_four_stats']+=1;continue
        c['cdb_research_candidate_existing_equal_cells']+=e
        c['cdb_research_candidate_existing_conflict_cells']+=conf
        c['cdb_research_candidate_null_cells']+=n
        canonical_candidates[row['match_id']].append((source['family'],source['line'],sc,n,e,conf))
    c['cdb_candidate_match_ids']=len(canonical_candidates)
    c['source_reused_by_multiple_cdb_match_ids']=0
    seen=collections.defaultdict(list)
    for mid,v in canonical_candidates.items():
        for fam,line,sc,n,e,conf in v:seen[(fam,line)].append((mid,sc,n,e,conf))
    for v in seen.values():
        if len(v)>1:c['source_reused_by_multiple_cdb_match_ids']+=1
    for mid,v in canonical_candidates.items():
        if len(v)!=1 or not v[0][2]:continue
        fam,line,sc,n,e,conf=v[0]
        if len(seen[(fam,line)])!=1:continue
        c['cdb_1to1_research_full_score_matches']+=1
        c['cdb_1to1_full_score_existing_equal_cells']+=e
        c['cdb_1to1_full_score_existing_conflict_cells']+=conf
        c['cdb_1to1_full_score_null_cell_opportunities']+=n
    # ALWAYS ZERO without independent cross-namespace original event ID evidence.
    return c

def main():
    import pandas as pd
    p=argparse.ArgumentParser();p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--cdb-parquet',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();blob=a.cdb_parquet.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=CDB_2025_SHA:raise ValueError('CURRENT_CDB_SHA_MISMATCH')
    source,index,sc=read_sources(a.source_dir)
    cols=['match_id','tour','scheduled_at','player1_id','player2_id','player1_name','player2_name','winner_id','status','tournament','round_name','stats_json']
    canonical=pd.read_parquet(a.cdb_parquet,columns=cols)
    if len(canonical)!=90571:raise ValueError('CDB_COUNT_CHANGED_EXPECTED_90571')
    c=analyze(source,index,canonical)
    report={'schema':'BLINQ_SACKMANN2025_VS_CDB2025_RESEARCH_COMPARISON_V1','source_archive_sha256':ARCHIVE_SHA,
     'source_mirror_commit':MIRROR_COMMIT,'source_2025_file_sha256':{p:info[2] for p,info in FILES.items()},
     'canonical_history_2025_sha256':CDB_2025_SHA,'canonical_rows':len(canonical),'counts':dict(sorted(c.items())),
     'source_counts':dict(sorted(sc.items())),'exact_source_to_provider_event_ids_attested':0,
     'source_to_canonical_event_ids_attested':0,'source_player_id_crosswalk_independent':False,
     'cdb_write_authorized':False,'safe_import_ready_fields':0,'cdb_rows_written':0,
     'source_current_match_stats_not_used_as_prematch_features':True,'provider_requests':0,
     'model_modified':False,'reason':'All metadata/score pairings are research only; no original independent provider event and both participant IDs, so no writer or canonical NULL promotion.'}
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('BLINQ_SACKMANN_CDB2025_AGGREGATE '+json.dumps(report,sort_keys=True))
if __name__=='__main__':main()
