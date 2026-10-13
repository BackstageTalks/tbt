#!/usr/bin/env python3
"""READ ONLY: challenge 2025 CDB player IDs with official Sofascore player URLs.

This proves ONLY whether the canonical provider player ID namespace agrees with
Sofascore for two named players. It never creates source-to-CDB match evidence
or grants source rights; it never writes CDB.
"""
from __future__ import annotations
import argparse, hashlib, json, re, unicodedata
from collections import defaultdict
from pathlib import Path

# Public official player URL ID vs unlicensed TennisData native ID (research only).
PUBLIC_TARGETS=(
    {'slug':'carlos_alcaraz','tour':'atp','tokens':('carlos','alcaraz'),'sofascore':'275923','season_native':'115728','url':'https://www.sofascore.com/tennis/player/alcaraz-carlos/275923'},
    {'slug':'aleksandr_shevchenko','tour':'atp','tokens':('shevchenko',),'sofascore':'264344','season_native':'345517','url':'https://www.sofascore.com/tennis/player/shevchenko-alexander/264344'},
    {'slug':'jannik_sinner','tour':'atp','tokens':('jannik','sinner'),'sofascore':'206570','url':'https://www.sofascore.com/tennis/player/sinner-jannik/206570'},
    {'slug':'novak_djokovic','tour':'atp','tokens':('novak','djokovic'),'sofascore':'14882','url':'https://www.sofascore.com/tennis/player/djokovic-novak/14882'},
    {'slug':'iga_swiatek','tour':'wta','tokens':('iga','swiatek'),'sofascore':'228272','url':'https://www.sofascore.com/tennis/player/swiatek-iga/228272'},
    {'slug':'aryna_sabalenka','tour':'wta','tokens':('aryna','sabalenka'),'sofascore':'157754','url':'https://www.sofascore.com/tennis/player/sabalenka-aryna/157754'},
)

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '').lower())
    return ' '.join(re.findall('[a-z]+',''.join(x for x in s if not unicodedata.combining(x))))

def name_matches_public_case(name, case):
    # Research-only namespace challenge: surname plus given-name initial,
    # never a player or match promotion. Accept full/abbreviated and both
    # ordered spellings only if the same uniquely stable original ID follows.
    tokens=norm(name).split()
    if len(tokens)<2:return False
    surname=case['tokens'][-1]
    first_initial={'carlos_alcaraz':'c','aleksandr_shevchenko':'a',
       'jannik_sinner':'j','novak_djokovic':'n','iga_swiatek':'i',
       'aryna_sabalenka':'a'}[case['slug']]
    if tokens[-1]==surname and tokens[0].startswith(first_initial):return True
    if tokens[0]==surname and tokens[-1].startswith(first_initial):return True
    return False

def assess(rows):
    counts={c['slug']:defaultdict(int) for c in PUBLIC_TARGETS}
    for row in rows:
        tour=str(row.get('tour') or '').lower()
        for side in ('1','2'):
            name=row.get('player'+side+'_name')
            pid=str(row.get('player'+side+'_id') or '')
            if not pid:continue
            for case in PUBLIC_TARGETS:
                if case['tour']==tour and name_matches_public_case(name,case):
                    counts[case['slug']][pid]+=1
    out={}
    for case in PUBLIC_TARGETS:
        matches=counts[case['slug']]
        total=sum(matches.values());ids=set(matches)
        out[case['slug']]={
          'occurrences':total,'distinct_cdb_player_ids':len(ids),
          'public_sofascore_id':case['sofascore'],
          'official_sofascore_player_url':case['url'],
          'sofascore_id_equal_to_cdb':len(ids)==1 and case['sofascore'] in ids and total>=2,
          'season_native_number_equal_to_cdb':len(ids)==1 and bool(case.get('season_native')) and case.get('season_native') in ids and total>=2,
          'canonical_id_consistent_across_matches':len(ids)==1 and total>=2,
          'canonical_IDs_undisclosed_in_public_log':True,
        }
    return {'schema':'BLINQ_CANONICAL_2025_PROVIDER_SOFA_ID_SPOTCHECK_V1',
        'result':out,'tested_original_provider_namespace_directly':False,
        'cross_provider_player_link_authorized':False,
        'source_match_bridge_authorized':False,
        'new_CDB_stat_cells_authorized':0,'new_CDB_cells_written':0,
        'note':'Two or more occurrences with surname+given initial and one numeric CDB ID. Public primary ID comparison only, never an event or license proof.'}


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--history',required=True,type=Path)
    ap.add_argument('--expected-sha256',required=True)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args()
    if not re.fullmatch('[0-9a-f]{64}',args.expected_sha256) or sha(args.history)!=args.expected_sha256:
        raise ValueError('CDB history-2025 SHA mismatch')
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(args.history)
    required=('tour','player1_id','player1_name','player2_id','player2_name')
    if not set(required)<=set(pf.schema.names):raise ValueError('CDB player columns missing')
    report=assess(row for chunk in pf.iter_batches(batch_size=1024,columns=list(required)) for row in chunk.to_pylist())
    report['cdb_partition_sha256']=args.expected_sha256
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    # Aggregate only: public output may include only two answer booleans.
    for slug,v in report['result'].items():
        print('BLINQ_SOFA_ID_SPOTCHECK '+json.dumps({'slug':slug,'occurrences':v['occurrences'],
          'consistent':v['canonical_id_consistent_across_matches'],
          'sofascore_match':v['sofascore_id_equal_to_cdb'],
          'tennisdata_match':v['season_native_number_equal_to_cdb']}))
if __name__=='__main__':main()
