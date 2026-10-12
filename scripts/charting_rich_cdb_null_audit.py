#!/usr/bin/env python3
"""Fail-closed private rich Charting gap analysis (NEVER writes CDB or approves an import)."""
import argparse,base64,collections,csv,gzip,hashlib,io,json,math,pathlib
import pyarrow.parquet as pq

SOURCE={"atp":("92d6975a09ebc0f5bf42d68a34e57087152e9219d8430d7794faa68b0c5630f8",15129),"wta":("cf1ec57c55cda20cd43a2848e30369b4c829486f618605c9a369a22fa3fdd315",8506)}
FIELDS={
"first_strike_serve_win":("servebasics_total_pts_won_lte_3_shots","servebasics_total_pts"),
"return_in_play_rate":("returnoutcomes_total_in_play","returnoutcomes_total_returnable"),
"return_deep_rate":("returndepth_total_deep","returndepth_total_returnable"),
"break_point_serve_win":("keypointsserve_bp_pts_won","keypointsserve_bp_pts"),
"break_point_return_win":("keypointsreturn_bpo_pts_won","keypointsreturn_bpo_pts"),
"net_points_win":("netpoints_netpoints_pts_won","netpoints_netpoints_net_pts"),
}

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()

def count(v):
    if v is None or v=="" or isinstance(v,bool):return None
    try:
        x=float(v)
        return x if math.isfinite(x) and x>=0 and x==int(x) else None
    except (ValueError,TypeError):return None

def rate(row,num,den):
    a=count(row.get(num));b=count(row.get(den))
    if a is None or b is None or b<=0 or a>b:return None
    return a/b

def run(project,out):
    project=pathlib.Path(project);out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True)
    src=pathlib.Path('private-data/tennis/charting');h=project/'history';review=project/'basic-gate'
    basic=json.loads((review/'report.json').read_text())
    assert basic['status']=='READ_ONLY_NO_PRODUCTION_WRITES'
    valid=[json.loads(s) for s in (review/'already_present_verified.jsonl').read_text().splitlines() if s.strip()]
    assert len(valid)==basic['consistent_already_present_rows']==662
    ids={x['canonical_match_id'] for x in valid}
    assert len(ids)==len(valid)
    # Read current CDB only; a source from a different release generation fails shut.
    baseline={}
    fields=['match_id','tour','scheduled_at','player1_id','player2_id','winner_id','status','stats_json','provider_context_json']
    for p in h.glob('history-*.parquet'):
        reader=pq.ParquetFile(p)
        assert set(fields)<=set(reader.schema.names)
        for batch in reader.iter_batches(batch_size=8192,columns=fields):
            for r in batch.to_pylist():
                mid=str(r['match_id'])
                if mid in ids:
                    assert mid not in baseline
                    baseline[mid]=r
    assert len(baseline)==len(ids)
    wanted=collections.defaultdict(set)
    for x in valid:wanted[x['source_match_id']].add(x['canonical_match_id'])
    # Reconstruct pinned 335-column raw-source views, not synthetic profile aggregates.
    selected=collections.defaultdict(list)
    root=pathlib.Path('private-data/research/offline-sources/blinq-import-2026-10-07/chunks')
    for tour,(expected,nrows) in SOURCE.items():
        paths=sorted(root.glob('blinq_charting_'+tour+'_core_features.csv.gz.b64.part*.txt'))
        assert paths
        b64=b''.join(p.read_bytes().strip() for p in paths)
        decoded=gzip.decompress(base64.b64decode(b64,validate=True))
        assert hashlib.sha256(decoded).hexdigest()==expected
        reader=csv.DictReader(io.StringIO(decoded.decode('utf-8-sig')))
        assert set(['match_id','player','opponent'])<=set(reader.fieldnames)
        assert set(y for pair in FIELDS.values() for y in pair)<=set(reader.fieldnames)
        countrows=0
        for row in reader:
            countrows+=1
            if row['match_id'] in wanted:
                selected[(tour,row['match_id'],row['player'])].append(row)
        assert countrows==nrows,(tour,countrows,nrows)
    with gzip.open(src/'matches.json.gz','rt') as stream:source_matches=json.load(stream)
    counters=collections.Counter();proposals=[]
    for x in valid:
        mid=x['canonical_match_id'];sid=x['source_match_id'];match=baseline[mid]
        cause=None;source=source_matches.get(sid);values={}
        if not source or len(source['players'])!=2:cause='source_match_missing'
        elif x['canonical_player_ids']!=[str(match['player1_id']),str(match['player2_id'])]:cause='canonical_ids_changed'
        elif hashlib.sha256(match['stats_json'].encode()).hexdigest()!=x['canonical_raw_stats_sha256']:cause='canonical_cells_changed'
        else:
            for i,name in enumerate(source['players']):
                rows=selected[(source['tour'],sid,name)]
                if len(rows)!=1:cause='rich_row_missing_or_duplicate';break
                row=rows[0]
                if row['opponent']!=source['players'][1-i]:cause='rich_wrong_opponent';break
                for feature,(n,d) in FIELDS.items():
                    v=rate(row,n,d)
                    if v is not None:
                        values['p'+str(x['source_player_side_map'][i])+'_'+feature]=v
        if cause is None:
            if not values:cause='no_safe_rich_ratios'
            else:
                cdb=json.loads(match['stats_json'])
                contradictions={k for k,v in values.items() if cdb.get(k) is not None and abs(float(cdb[k])-v)>1e-6}
                if contradictions:cause='rich_existing_stats_conflict'
        if cause is None:
            nulls={k:v for k,v in values.items() if cdb.get(k) is None}
            counters['compared_rich_cells']+=len(values)
            counters['identical_rich_cells_already_present']+=len(values)-len(nulls)
            if not nulls:cause='rich_fields_already_present'
        counters[cause or 'nonconflicting_rich_nulls_require_final_event_proof']+=1
        if cause is None:
            ctx=json.loads(match['provider_context_json'] or '{}')
            proposals.append({'source_match_id':sid,'canonical_match_id':mid,'canonical_player_ids':x['canonical_player_ids'],'utc_year':int(str(match['scheduled_at'])[:4]),'incoming_stats':nulls,'existing_rich_corrob':sorted(k for k in values if k not in nulls),'provider_context_keys':sorted(ctx)[:30],'independent_event_id_present':bool(ctx.get('_tbt_provider_event_id')),'source_sha256':x['source_sha256'],'canonical_raw_stats_sha256':x['canonical_raw_stats_sha256'],'import_ready':False})
    countfields=sum(len(p['incoming_stats']) for p in proposals)
    result={'schema':1,'status':'READ_ONLY_RICH_NULL_GATE','consistent_basic_match_candidates':len(valid),'rich_field_count':len(FIELDS)*2,'counts':dict(counters),'possible_rich_rows':len(proposals),'possible_rich_cells':countfields,'with_provider_event_id':sum(bool(p['independent_event_id_present']) for p in proposals),'approved_production_rows':0,'written_production_cells':0,'next_gate':'Verify independently sourced provider event and both player IDs, whole-match point coverage, source as-of, global lock, immutable backup, CAS and persisted readback'}
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    with (out/'proposals.jsonl').open('w') as f:
        for x in proposals:f.write(json.dumps(x,sort_keys=True)+'\n')
    print('CHARTING_RICH_NULL_GATE',json.dumps(result,sort_keys=True))
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--project',required=True);a.add_argument('--out',required=True);v=a.parse_args();run(v.project,v.out)
