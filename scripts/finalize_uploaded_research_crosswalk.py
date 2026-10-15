#!/usr/bin/env python3
"""Refresh native-event / canonical match CROSSWALK for private research only.

Never authorizes canonical writes or training. Source reuse rights must be
independently cleared before any separate guarded import. Any duplicate source,
canonical target, or stale proof is excluded, not arbitrarily resolved.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path

BASELINE_CANDIDATES_SHA='4efc0e0b0f5ff9272f39f7ba8ca55c5b7b85981bf3dd192ff8c974cf0c9114b1'
SOURCE_SHA='e66e6de58d70801fe2dca7b049f75f442237516a7e5042947b892d63daa1dae8'
INDEX_SHA='328f9c36c0f4021c745ca7119ea904a4ae7cadb66cee17cc63f2ca6f5774a952'
RIGHTS='UNVERIFIED_PRIVATE_RESEARCH_ONLY'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def read_jsonl_gz(path):
    with gzip.open(path,'rt',encoding='utf8') as f:
        for n,line in enumerate(f,1):
            if line.strip():
                obj=json.loads(line,parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
                if not isinstance(obj,dict):raise ValueError('Non-object JSON at '+str(n))
                yield obj

def key(row):return (str(row.get('source_key') or ''),str(row.get('canonical_match_id') or ''))

def unique_or_reject(fresh,baseline,source_index):
    """Fail closed for ambiguous identity/target; keep only prior-proof-consistent rows."""
    bkeys=Counter(key(x) for x in baseline)
    fkeys=Counter(key(x) for x in fresh)
    source_owners=Counter(str(x.get('source_key') or '') for x in fresh)
    target_owners=Counter(str(x.get('canonical_match_id') or '') for x in fresh)
    source_proof=Counter(str(x.get('source_key') or '') for x in source_index)
    reasons=Counter();ready=[]
    for r in fresh:
        sk,mid=key(r)
        checks=[
            (not sk or not mid,'empty_identity'),
            (bkeys[(sk,mid)]!=1,'not_unique_in_prior_attested_audit'),
            (fkeys[(sk,mid)]!=1,'repeated_current_candidate'),
            (source_owners[sk]!=1,'ambiguous_source_owner'),
            (target_owners[mid]!=1,'ambiguous_canonical_target'),
            (source_proof[sk]!=1,'duplicate_or_missing_source_provenance'),
            (not isinstance(r.get('new_null_keys'),list) or not r['new_null_keys'],'no_missing_nulls'),
            (bool(r.get('new_null_keys')) and (len(r['new_null_keys'])!=len(set(r['new_null_keys']))),'duplicate_stat_keys'),
        ]
        reject=next((why for wrong,why in checks if wrong),None)
        if reject:
            reasons[reject]+=1;continue
        source=next(x for x in source_index if x.get('source_key')==sk)
        ready.append({
            'schema':1,
            'source_tour':str(source.get('source_tour') or ''),
            'source_match_id':str(source.get('source_match_id') or ''),
            'source_key':sk,
            'canonical_match_id':mid,
            'matched_via':'native_flashscore_event_both_players_winner_score_four_count_proof',
            'source_minus_index_seconds':r['source_minus_index_seconds'],
            'source_minus_canonical_seconds':r['source_minus_canonical_seconds'],
            'null_stat_names_at_snapshot':sorted(r['new_null_keys']),
            'rights_status':RIGHTS,
            'source_reuse_authorized':False,
            'canonical_import_ready':False,
            'write_authorized':False,
            'prematch_feature_allowed':False,
            'model_training_allowed':False,
            'source_sha256':SOURCE_SHA,
            'independent_index_sha256':INDEX_SHA,
            'baseline_audit_candidates_sha256':BASELINE_CANDIDATES_SHA,
            'note':'Identity link is a research hypothesis independently corroborated at current snapshot; never an import authorization.',
        })
    ready.sort(key=lambda x:(x['source_tour'],x['source_match_id'],x['canonical_match_id']))
    return ready,reasons

def run(source,index,history,baseline,out):
    from audit_uploaded_clock_bridge import run as current_probe
    source,index,history,baseline,out=map(Path,(source,index,history,baseline,out))
    if digest(source)!=SOURCE_SHA or digest(index)!=INDEX_SHA or digest(baseline)!=BASELINE_CANDIDATES_SHA:
        raise ValueError('Source/index/baseline proof digest mismatch')
    out.mkdir(parents=True,exist_ok=True)
    probe_dir=out/'current-audit'
    current=current_probe(source,index,history,probe_dir)
    fresh=list(read_jsonl_gz(probe_dir/'private-candidates.jsonl.gz'))
    older=list(read_jsonl_gz(baseline))
    sources=list(read_jsonl_gz(source))
    links,why=unique_or_reject(fresh,older,sources)
    # Fail-closed: baseline must itself be a unique source/canonical list.
    if len(older)!=139 or len(set(map(key,older)))!=len(older):
        raise ValueError('Baseline audit evidence inconsistent')
    if sum(len(r['null_stat_names_at_snapshot']) for r in links)>current['counts'].get('potential_new_null_cells',0):
        raise ValueError('Proposed research links exceed freshly proven missing cells')
    # A deterministic gzip for pinned immutable research evidence.
    dst=out/'research-native-links.jsonl.gz'
    with dst.open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as gz:
            gz.write(''.join(json.dumps(x,sort_keys=True,ensure_ascii=False)+'\n' for x in links).encode())
    report={
        'schema':'BLINQ_VERIFIED_PRIVATE_NATIVE_CROSSWALK_REFRESH_V1',
        'status':'READ_ONLY_RESEARCH_CROSSWALK_NO_CANONICAL_WRITE',
        'baseline_run_id':38704795156,
        'source_sha256':SOURCE_SHA,
        'independent_index_sha256':INDEX_SHA,
        'prior_candidate_asset_sha256':BASELINE_CANDIDATES_SHA,
        'canonical_partitions_sha256':current['canonical_pins'],
        'prior_candidates':len(older),'fresh_candidates_before_dedupe':len(fresh),
        'fresh_null_cells_before_dedupe':current['counts'].get('potential_new_null_cells',0),
        'research_links_unique':len(links),
        'research_null_stat_keys':sum(len(x['null_stat_names_at_snapshot']) for x in links),
        'disqualified_after_dedupe':dict(sorted(why.items())),
        'stale_or_no_longer_relevant_prior_candidates':len(set(map(key,older))-set(map(key,fresh))),
        'source_rights_status':RIGHTS,
        'canonical_writes':0,'canonical_import_authorized':False,
        'prematch_feature_allowed':False,'model_training_allowed':False,
        'research_asset_sha256':digest(dst),
    }
    (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--index',type=Path,required=True)
    p.add_argument('--history',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.source,a.index,a.history,a.baseline,a.out),sort_keys=True))
if __name__=='__main__':main()