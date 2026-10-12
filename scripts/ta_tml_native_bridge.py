#!/usr/bin/env python3
"""Strict TA match-log to historical TML CSV source-native corroboration.

READ ONLY.  A numerical suffix of a Tennis Abstract matchid is *not* a
TML/Sackmann match_num. Both sources may share historical lineage; agreement
is source-context evidence ONLY, never a canonical CDB identity witness.
"""
from __future__ import annotations
import argparse, csv, gzip, hashlib, json, re, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

TA_FIELDS=("aces","double_faults","service_points","first_serves_in",
           "first_serve_points_won","second_serve_points_won",
           "break_points_saved","break_points_faced")
TML_FIELDS=("ace","df","svpt","1stIn","1stWon","2ndWon","bpSaved","bpFaced")
ROUNDS={"F":"F","SF":"SF","QF":"QF","R128":"R128","R64":"R64",
        "R32":"R32","R16":"R16","Q1":"Q1","Q2":"Q2","Q3":"Q3",
        "RR":"RR","BR":"BR"}

def compact(v):
    s=unicodedata.normalize('NFKD',str(v or '')).lower()
    return ''.join(c for c in s if c.isascii() and c.isalnum())

def tourney_key(val):
    """Only canonicalize leading zeroes of numeric tournament suffixes."""
    match=re.fullmatch(r'(\d{4})-(\d+)',str(val))
    return match.group(1)+'-'+str(int(match.group(2))) if match else str(val)

def ta_tourney(mid):
    mid=str(mid or '')
    parts=mid.rsplit('-',1)
    if len(parts)!=2 or not parts[1].isdigit() or not re.match(r'^\d{4}-',parts[0]):
        return ''
    return tourney_key(parts[0])

def tml_index(paths):
    records=defaultdict(list); total=0
    for path in paths:
        with Path(path).open(newline='',encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                total+=1
                two=(compact(r.get('winner_name')),compact(r.get('loser_name')))
                if not all(two) or two[0]==two[1]:continue
                round_=str(r.get('round') or '').upper()
                key=(tourney_key(r.get('tourney_id')),tuple(sorted(two)),round_)
                records[key].append(r)
    return records,total

def candidate_history_id(row):
    """Historical fingerprint hint for 2022–25; NOT canonical existence proof."""
    year=str(row.get('tourney_id') or '')[:4]
    if year not in ('2022','2023','2024','2025'):
        return None
    tid=str(row.get('tourney_id') or '')
    number=str(row.get('match_num') or '')
    rd=str(row.get('round') or '').lower()
    if not tid or not number.isdigit() or not rd:
        return None
    def name(s):
        v=unicodedata.normalize('NFKD',str(s or '')).lower()
        v=''.join(c for c in v if not unicodedata.combining(c))
        return ' '.join(re.findall(r'[a-z0-9]+',v))
    names=sorted((name(row.get('winner_name')),name(row.get('loser_name'))))
    if not all(names) or names[0]==names[1]:return None
    composite='|'.join(('atp','main',tid,number,rd,'|'.join(names)))
    return 'hist-js:atp:'+hashlib.sha256(composite.encode()).hexdigest()[:24]

def _nums(row,side):
    values={}
    for ta,k in zip(TA_FIELDS,TML_FIELDS):
        raw=str(row.get(f'{side}_{k}') or '').strip()
        if not raw.isdigit():return None
        values[ta]=int(raw)
    return values

def compare(ta,tml):
    src=ta.get('source_stats_counts') or {}
    source_a=compact(ta.get('source_side_a_profile_slug'))
    source_b=compact(ta.get('source_side_b_opponent_normalized_name'))
    winner=compact(tml.get('winner_name')); loser=compact(tml.get('loser_name'))
    if (source_a,source_b)==(winner,loser):p1,p2='w','l'
    elif (source_a,source_b)==(loser,winner):p1,p2='l','w'
    else:return 'PLAYER_ORIENTATION_MISMATCH',0
    left=_nums(tml,p1);right=_nums(tml,p2)
    if left is None or right is None:return 'TML_MISSING_WHOLE_MATCH_COUNTS',0
    missing=[]
    for k in TA_FIELDS:
        if k not in src or 'opp_'+k not in src: missing.append(k)
    if missing:return 'TA_MISSING_COUNT_EVIDENCE',0
    evidence=sum(1 for k in TA_FIELDS if src[k]==left[k]) + sum(1 for k in TA_FIELDS if src['opp_'+k]==right[k])
    return ('SOURCE_COUNTS_EXACT' if evidence==2*len(TA_FIELDS) else 'SOURCE_COUNT_CONFLICT'),evidence

def audit(ta_path, tml_paths, out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    idx,total=tml_index(tml_paths);c=Counter();accepted=[];conflicts=[]
    with gzip.open(ta_path,'rt',encoding='utf-8') as f:
        for line in f:
            if not line.strip():continue
            r=json.loads(line);c['ta_rows']+=1
            if r.get('import_ready') is not False or r.get('canonical_match_id') is not None:
                raise ValueError('TA staging unexpectedly authorizes canonical writes')
            if r.get('source_tour')!='atp':c['not_atp']+=1;continue
            if (r.get('perspectives')!=2 or r.get('source_perspectives_mirrored') is not True):
                c['not_mirrored_both_profiles']+=1;continue
            tid=ta_tourney(r.get('ta_matchid'))
            rd=str(r.get('round') or '').upper()
            a=compact(r.get('source_side_a_profile_slug'))
            b=compact(r.get('source_side_b_opponent_normalized_name'))
            if not tid or not a or not b or a==b or rd not in ROUNDS:
                c['unkeyed_or_unsupported_round']+=1;continue
            key=(tid,tuple(sorted((a,b))),rd)
            candidates=idx.get(key,[])
            if not candidates:c['no_native_context_match']+=1;continue
            if len(candidates)!=1:
                c['ambiguous_native_context_match']+=1;continue
            row=candidates[0]
            if not str(row.get('match_num') or '').isdigit():
                c['missing_tml_native_match_num']+=1;continue
            status,fields=compare(r,row)
            c[status]+=1
            if status=='SOURCE_COUNTS_EXACT':
                accepted.append({'ta_source_event_candidate_key':r['source_event_candidate_key'],
                                 'ta_matchid':r['ta_matchid'],
                                 'tml_tourney_id':row['tourney_id'],
                                 'tml_match_num':row['match_num'],
                                 'tml_winner_id':row['winner_id'],
                                 'tml_loser_id':row['loser_id'],
                                 'source_counts_equal':fields,
                                 'candidate_unverified_hist_js_match_id':candidate_history_id(row),
                                 'context_round':rd,
                                 'context_tournament_start_date':row['tourney_date'],
                                 'canonical_match_id':None,
                                 'independent_event_identity_proven':False,
                                 'source_reuse_rights_verified':False,
                                 'import_ready':False,'cdb_write_authorized':False})
            else:
                conflicts.append({'ta_source_event_candidate_key':r['source_event_candidate_key'],
                                  'ta_matchid':r['ta_matchid'],
                                  'tml_tourney_id':row['tourney_id'],
                                  'tml_match_num':row['match_num'],
                                  'reason':status,'equal_counts':fields})
    out_file=out/'native_source_agreement_review.jsonl.gz'
    with gzip.open(out_file,'wt',encoding='utf-8') as f:
        for row in accepted:f.write(json.dumps(row,sort_keys=True)+'\n')
    with (out/'count_conflicts_review.jsonl').open('w',encoding='utf-8') as f:
        for row in conflicts:f.write(json.dumps(row,sort_keys=True)+'\n')
    h=hashlib.sha256()
    with open(ta_path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    rep={'status':'SOURCE_NATIVE_MATCH_REVIEW_ONLY_NO_CDB_WRITE','source_sha256':h.hexdigest(),
         'tml_raw_rows':total,'counts':dict(c),'native_agreement_rows':len(accepted),
         'canonical_match_ids_verified':0,'current_cdb_null_fields_verified':0,
         'source_reuse_rights_verified':False,'cdb_written_cells':0,
         'warning':'TA matchid numeric suffix != TML match_num. This is same-lineage source corroboration, not independent canonical identity or license.'}
    (out/'report.json').write_text(json.dumps(rep,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return rep

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ta',type=Path,required=True);p.add_argument('--tml',nargs='+',required=True,type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(audit(a.ta,a.tml,a.out),ensure_ascii=False))