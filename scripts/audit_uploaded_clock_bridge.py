#!/usr/bin/env python3
"""Fail-closed, read-only audit of same-native-event start-time discrepancies.

Uses a SHA-pinned Flashscore 2026 event index, SHA-pinned original upload
stage, and independently SHA-pinned current canonical 2024-2026 partitions.
Never writes CDB, never authorizes an import, never creates a model feature.
"""
from __future__ import annotations
import argparse, collections, datetime, gzip, hashlib, json, math
from pathlib import Path

SOURCE_SHA='e66e6de58d70801fe2dca7b049f75f442237516a7e5042947b892d63daa1dae8'
INDEX_SHA='328f9c36c0f4021c745ca7119ea904a4ae7cadb66cee17cc63f2ca6f5774a952'
EXACT_COUNTS=('p1_aces','p2_aces','p1_double_faults','p2_double_faults')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(path):
    with gzip.open(path,'rt',encoding='utf8') as h:
        for line in h:
            if line.strip():yield json.loads(line)

def parse_utc(v):
    try:
        x=datetime.datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return x.astimezone(datetime.timezone.utc) if x.tzinfo else None
    except (ValueError,TypeError):return None

def json_obj(v):
    if isinstance(v,dict):return v
    try:
        x=json.loads(v)
        return x if isinstance(x,dict) else {}
    except (ValueError,TypeError):return {}

def seconds(a,b):
    x,y=parse_utc(a),parse_utc(b)
    return int((x-y).total_seconds()) if x and y else None

def run(source,index,history,out):
    import pyarrow.parquet as pq
    from link_uploaded_flashscore_verified import norm,short_matches,score_two_sets
    source,index,history,out=map(Path,(source,index,history,out))
    if sha(source)!=SOURCE_SHA or sha(index)!=INDEX_SHA:raise ValueError('Source/index digest mismatch')
    bundle=json.loads((history/'_tbt_bundle_manifest.json').read_text())['files']
    history_manifest=json.loads((history/'history_manifest.json').read_text())['years']
    can={};seen=set();checks={}
    fields=('match_id','tour','scheduled_at','player1_id','player2_id','player1_name','player2_name','winner_id','surface','best_of','status','stats_json','tournament')
    for year in (2024,2025,2026):
        p=history/f'history-{year}.parquet';digest=sha(p)
        if bundle[p.name]['sha256']!=digest or history_manifest[str(year)]['sha256']!=digest:raise ValueError('CDB manifests do not pin snapshot')
        checks[p.name]=digest
        pf=pq.ParquetFile(p)
        for batch in pf.iter_batches(batch_size=4096,columns=list(fields)):
            for r in batch.to_pylist():
                mid=str(r['match_id'])
                if mid in seen:raise ValueError('Canonical duplicate ID')
                seen.add(mid);can[mid]=r
    idx=collections.defaultdict(list)
    for o in rows(index):
        if o.get('event_id'):idx[str(o['event_id'])].append(o)
    ct=collections.Counter();times=collections.Counter();possibilities=[];other=[]
    for s in rows(source):
        ct['source_rows']+=1
        eid=str(s['source_match_id']); candidates=idx.get(eid,[])
        if len(candidates)!=1:
            ct['index_missing_or_ambiguous']+=1;continue
        i=candidates[0];mid=str(i.get('canonical_match_id') or '')
        if not mid or not isinstance(i.get('link'),dict) or i['link'].get('accepted') is not True or i['link'].get('orientation') not in ('direct','swapped'):
            ct['index_bridge_not_attested']+=1;continue
        c=can.get(mid)
        if c is None:ct['not_in_current_cdb']+=1;continue
        if str(c['tour']).upper()!=s['source_tour'] or str(i.get('tour','')).upper()!=s['source_tour']:
            ct['tour_disagrees']+=1;continue
        src_utc=s['scheduled_at_utc']; ci=str(c['scheduled_at']); ii=i.get('start_utc')
        if parse_utc(src_utc) is None or parse_utc(ci) is None or parse_utc(ii) is None:
            ct['invalid_clock']+=1;continue
        di=seconds(src_utc,ii);dc=seconds(src_utc,ci)
        if di==dc==0:ct['strict_3way_utc']+=1
        else:
            ct['clock_diff_with_same_native_event']+=1
            if max(abs(di),abs(dc)) <= 3600:times['upto_1h']+=1
            elif max(abs(di),abs(dc)) <= 3600*6:times['upto_6h']+=1
            elif max(abs(di),abs(dc)) <= 3600*24:times['upto_24h']+=1
            else:times['above_24h']+=1
        if not all(abs(v)<=24*3600 for v in (di,dc)):
            ct['clock_over_24h']+=1;continue
        if str(c['status']).lower() not in ('finished','completed','ended'):
            ct['canonical_unfinished']+=1;continue
        p1,p2=norm(i.get('player1_source')),norm(i.get('player2_source'))
        w,l=norm(s['source_winner_name']),norm(s['source_loser_name'])
        if not p1 or p1==p2 or {p1,p2}!={w,l}:
            ct['source_index_players_disagree']+=1;continue
        winner_first=((p1==w)==(i['link']['orientation']=='direct'))
        cw=c['player1_name'] if winner_first else c['player2_name'];cl=c['player2_name'] if winner_first else c['player1_name']
        if not short_matches(cw,s['source_winner_name']) or not short_matches(cl,s['source_loser_name']):
            ct['canonical_players_disagree']+=1;continue
        if str(c['winner_id'])!=str(c['player1_id'] if winner_first else c['player2_id']):
            ct['canonical_winner_disagrees']+=1;continue
        if str(c['surface']).casefold()!=s['source_surface'].casefold():
            ct['surface_disagrees']+=1;continue
        if s['source_best_of']!=3 or (c['best_of'] is not None and not math.isnan(float(c['best_of'])) and int(c['best_of'])!=3):
            ct['format_disagrees']+=1;continue
        score=score_two_sets(s['source_score'])
        if not score:ct['score_not_complete_two_sets']+=1;continue
        stats=json_obj(c['stats_json']);match_score=True
        for sn,(wg,lg) in enumerate(score,1):
            for side,games in (('p1',wg if winner_first else lg),('p2',lg if winner_first else wg)):
                if stats.get(f'{side}_set{sn}_games') is None or float(stats[f'{side}_set{sn}_games'])!=games:
                    match_score=False
        if not match_score:ct['canonical_independent_score_missing_or_conflict']+=1;continue
        incoming={}
        for who,values in (('winner',s['winner_stats']),('loser',s['loser_stats'])):
            prefix='p1' if (who=='winner')==winner_first else 'p2'
            for k,v in values.items():incoming[f'{prefix}_{k}']=float(v)
        if not all(k in incoming and stats.get(k) is not None and float(stats[k])==incoming[k] for k in EXACT_COUNTS):
            ct['four_independent_counts_missing_or_conflict']+=1;continue
        ct['proven_same_native_event_players_score_four_stats']+=1
        conflict=[k for k,v in incoming.items() if stats.get(k) is not None and abs(float(stats[k])-v)>1e-6]
        if conflict:
            ct['other_stats_conflict']+=1;other.append({'source_key':s['source_key'],'conflicting_keys':conflict});continue
        missing={k:v for k,v in incoming.items() if stats.get(k) is None}
        if not missing:ct['already_complete']+=1;continue
        ct['staged_candidate_matches']+=1;ct['potential_new_null_cells']+=len(missing)
        possibilities.append({'source_key':s['source_key'],'canonical_match_id':mid,'new_null_keys':sorted(missing),
                              'source_minus_index_seconds':di,'source_minus_canonical_seconds':dc,
                              'verified_proof':'same native Flashscore event, exact two oriented players, canonical winner, full two-set canonical score, four existing count cells; SOURCE ONLY NOT WRITER AUTHORIZED'})
    out.mkdir(parents=True,exist_ok=True)
    report={'schema':1,'status':'READ_ONLY_CANDIDATES_NOT_AUTHORIZED',
            'counts':dict(ct),'clock_discrepancy_buckets':dict(times),'canonical_pins':checks,
            'source_sha256':SOURCE_SHA,'index_sha256':INDEX_SHA,
            'canonical_cells_written':0,'model_training':False,
            'potential_candidates_not_import_ready':len(possibilities)}
    (out/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    # Private, non-exportable per-match identities retained only in private artifact.
    with gzip.open(out/'private-candidates.jsonl.gz','wt',encoding='utf8') as f:
        for item in possibilities:f.write(json.dumps(item,sort_keys=True)+'\n')
    with gzip.open(out/'private-conflicts.jsonl.gz','wt',encoding='utf8') as f:
        for item in other:f.write(json.dumps(item,sort_keys=True)+'\n')
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',required=True)
    p.add_argument('--index',required=True)
    p.add_argument('--history',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(run(a.source,a.index,a.history,a.out),sort_keys=True))

if __name__=='__main__':main()