"""Measure source value without fuzzy identity promotion or production writes.

Separates algebraic recovery from existing CDB rates from source-native historical
lineage and external-only candidate cells. Historical lineage is NOT an attested
cross-provider bridge. Produces private review ledgers, never writer input.
"""
import argparse,collections,csv,gzip,hashlib,json,math,re,unicodedata
from pathlib import Path

PAIRS=tuple((f'{side}_{serve}',f'{opp}_{ret}')
    for side,opp in (('p1','p2'),('p2','p1'))
    for serve,ret in (('first_serve_win','first_return_win'),
                      ('second_serve_win','second_return_win'),
                      ('service_points_won','return_points_won')))

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def rate(x):
    return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x) and 0<=x<=1

def derive(stats):
    additions={};evidence={}
    for a,b in PAIRS:
        x,y=stats.get(a),stats.get(b)
        if any(v is not None and not rate(v) for v in (x,y)):
            return {},{},'invalid_rate'
        if x is not None and y is not None and abs(x+y-1)>1e-6:
            return {},{},'contradictory_complements'
        for target,source in ((a,b),(b,a)):
            if stats.get(target) is None and stats.get(source) is not None:
                additions[target]=1-stats[source]
                evidence[target]={'field':source,'value':stats[source],'formula':'1 - opponent_rate'}
    return additions,evidence,None

def norm(x):
    x=unicodedata.normalize('NFKD',str(x or ''))
    return ' '.join(re.sub('[^a-z0-9]+',' ',''.join(c for c in x if not unicodedata.combining(c)).lower().replace('_',' ')).split())

def historical_id(tour,filename,row):
    kind='main'
    if tour=='atp':
        for token in ('qual_chall','futures','amateur'):
            if token in filename:kind=token;break
    round_=norm(row['round'])
    round_={'final':'f','the final':'f','semifinal':'sf','semifinals':'sf',
            'quarterfinal':'qf','quarterfinals':'qf','round robin':'rr',
            **{f'round of {n}':f'r{n}' for n in (16,32,64,128)}}.get(round_,round_)
    key='|'.join((tour,kind,row['tourney_id'],row['match_num'],round_,
                  '|'.join(sorted((norm(row['winner_name']),norm(row['loser_name']))))))
    return f'hist-js:{tour}:'+hashlib.sha256(key.encode()).hexdigest()[:24],kind

def obj(raw):
    if raw is None:return {}
    d=json.loads(raw) if isinstance(raw,str) else raw
    if not isinstance(d,dict):raise ValueError('Invalid JSON object')
    return d

def run(cdb,source,candidates,audit,out):
    import pyarrow.parquet as pq
    out.mkdir(parents=True,exist_ok=True)
    report=json.loads(audit.read_text())
    if sha(candidates)!=report['candidate_ledger_sha256']:raise ValueError('Candidate SHA mismatch')
    manifest=json.loads((cdb/'history_manifest.json').read_text())
    if sha(cdb/'history_manifest.json')!=report['canonical_manifest_sha256']:raise ValueError('CDB snapshot drift')
    wanted={};by_file=collections.defaultdict(dict)
    with gzip.open(candidates,'rt',encoding='utf-8') as f:
        for line in f:
            r=json.loads(line);mid=r['canonical_match_id_candidate']
            if mid in wanted or r['write_authorized'] is not False:raise ValueError('Bad candidate ledger')
            wanted[mid]=r;by_file[r['source_file']][r['source_record_number']]=mid
    originals={}
    for relative,indices in by_file.items():
        path=source/relative
        if sha(path)!=report['source_file_sha256'][relative]:raise ValueError('Source drift')
        with path.open(encoding='utf-8-sig',newline='') as f:
            for number,row in enumerate(csv.DictReader(f),1):
                if number in indices:originals[indices[number]]=row
    if len(originals)!=len(wanted):raise ValueError('Missing source rows')
    counts=collections.Counter();fields=collections.Counter();seen=set();seen_candidates=set()
    recovery=out/'canonical-complement-research.jsonl.gz'
    routes=out/'source-value-routes.jsonl.gz'
    with gzip.open(recovery,'wt',encoding='utf-8') as recovery_file,gzip.open(routes,'wt',encoding='utf-8') as route_file:
        for year,meta in sorted(manifest['years'].items()):
            part=cdb/f'history-{year}.parquet'
            if sha(part)!=meta['sha256']:raise ValueError('Partition SHA mismatch')
            pf=pq.ParquetFile(part)
            columns=['match_id','tour','scheduled_at','status','player1_id','player2_id',
                     'player1_name','player2_name','winner_id','provider_context_json','stats_json']
            for batch in pf.iter_batches(columns=columns,batch_size=8192):
                for c in batch.to_pylist():
                    mid=str(c['match_id'])
                    if not mid or mid in seen:raise ValueError('Canonical identity collision')
                    seen.add(mid);counts['canonical_rows']+=1
                    stats=obj(c['stats_json']);ctx=obj(c['provider_context_json'])
                    additions,evidence,error=derive(stats)
                    if str(c['status']).lower() not in ('completed','finished','ended'):
                        additions={};error='noncompleted'
                    if error:counts['complement_blocked_'+error]+=1
                    if additions:
                        counts['canonical_complement_matches']+=1
                        counts['canonical_complement_cells']+=len(additions);fields.update(additions.keys())
                        recovery_file.write(json.dumps({'match_id':mid,'partition_sha256':meta['sha256'],
                            'source_stats_sha256':hashlib.sha256(json.dumps(stats,sort_keys=True).encode()).hexdigest(),
                            'additions':additions,'evidence':evidence,'write_authorized':False,
                            'usage':'postmatch_only_no_model_activation'})+'\n')
                    if mid not in wanted:continue
                    seen_candidates.add(mid);r=wanted[mid];raw=originals[mid]
                    proposed=r['missing_candidate_cells'];overlap={k for k in proposed if k in additions}
                    exact={k for k in overlap if abs(proposed[k]-additions[k])<=1e-6}
                    counts['candidate_cells_total']+=len(proposed)
                    counts['candidate_cells_recoverable_from_cdb']+=len(overlap)
                    counts['candidate_cells_cdb_recovery_agrees_exactly']+=len(exact)
                    counts['candidate_cells_cdb_recovery_differs']+=len(overlap-exact)
                    remaining=set(proposed)-overlap
                    counts['candidate_cells_requiring_external_values']+=len(remaining)
                    expected,kind=historical_id(r['tour'],r['source_file'],raw)
                    lineage='NO_EXACT_HISTORICAL_LINEAGE'
                    if mid==expected:
                        counts['historical_key_reconstructed']+=1
                        source_marker=(ctx.get('_tbt_statistics') or {}).get('source')
                        provenance=(source_marker=='jeff_sackmann_match_snapshot:'+Path(r['source_file']).name
                            and ctx.get('_tbt_provider_event_id')==mid
                            and ctx.get('_tbt_source_category_name')=='historical_'+kind)
                        orientation=(norm(c['player1_name'])==norm(raw['winner_name'])
                            and norm(c['player2_name'])==norm(raw['loser_name'])
                            and str(c['winner_id'])==str(c['player1_id']))
                        native=(str(c['player1_id'])==f"hist-js:{r['tour']}:{raw['winner_id']}"
                            and str(c['player2_id'])==f"hist-js:{r['tour']}:{raw['loser_id']}")
                        same_day=c['scheduled_at'].strftime('%Y%m%d')==raw['tourney_date']
                        if provenance and orientation and same_day:
                            lineage='HISTORICAL_SOURCE_PROVENANCE_NATIVE_PLAYERS' if native else 'HISTORICAL_SOURCE_PROVENANCE_REMAPPED_PLAYERS'
                        else:lineage='RECONSTRUCTED_KEY_WITHOUT_FULL_PROVENANCE'
                    counts[lineage+'_matches']+=1
                    counts[lineage+'_external_cells']+=len(remaining)
                    route_file.write(json.dumps({'source_native_key':r['source_native_key'],
                        'canonical_match_id_candidate':mid,'lineage':lineage,
                        'cdb_recoverable_fields':sorted(overlap),'external_value_fields':sorted(remaining),
                        'independent_provider_identity':False,'write_authorized':False})+'\n')
    if seen_candidates!=set(wanted):raise ValueError('Candidate targets missing')
    result={'schema':1,'state':'VERIFIED_VALUE_ROUTE_AUDIT_NOT_A_WRITER',
            'canonical_manifest_sha256':report['canonical_manifest_sha256'],
            'input_candidates_sha256':sha(candidates),'counts':dict(sorted(counts.items())),
            'canonical_complement_fields':dict(sorted(fields.items())),
            'outputs':{p.name:sha(p) for p in (recovery,routes)},
            'production_writes':0,'model_changes':0,
            'limitation':'Lineage is source provenance, not independent provider identity. Complement cells are derived from existing canonical rates and add no independent information. No row is authorized for direct import.'}
    (out/'value-routes-report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('cdb','source','candidates','audit','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();run(a.cdb,a.source,a.candidates,a.audit,a.out)
