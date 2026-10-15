"""Read-only FIX4 ATP URL -> canonical event identity diagnostic.

No fuzzy identity promotion. Absence of canonical ATP-native event + both
original player ID attestation means NO write approval, by design.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,re,zipfile,collections,datetime
from pathlib import Path
from urllib.parse import urlsplit

EXPECTED_BRIDGE_ZIP='da4854ca582a0baae488f9874e608894b8757dcdf72c1379f9a1e2d53c37dff2'
OFFICIAL_URL=re.compile(r'^/en/scores/(?:match-stats/archive)/(\d{4})/(\d+)/([a-z0-9]+)$',re.I)
OFFICIAL_URL2=re.compile(r'^/en/scores/(\d{4})/(\d+)/([a-z0-9]+)/match-stats$',re.I)
OFFICIAL_ID=re.compile(r'^atptour:(\d{4}):(\d+):([a-z0-9]+)$',re.I)

def native_key(v):
    if not isinstance(v,str):return None
    v=v.strip(); mid=OFFICIAL_ID.fullmatch(v)
    if mid:return '/'.join(x.lower() for x in mid.groups())
    parsed=urlsplit(v)
    if parsed.hostname and parsed.hostname.lower() not in {'atptour.com','www.atptour.com'}:return None
    if not parsed.hostname and not v.startswith('/en/scores/'):return None
    if parsed.query or parsed.fragment:return None
    path=parsed.path.rstrip('/')
    match=OFFICIAL_URL.fullmatch(path) or OFFICIAL_URL2.fullmatch(path)
    return '/'.join(x.lower() for x in match.groups()) if match else None

def official_keys_from_context(v):
    if isinstance(v,str):
        try: v=json.loads(v)
        except (ValueError,TypeError):return set()
    keys=set()
    def walk(x,depth=0):
        if depth>6:return
        if isinstance(x,dict):
            for k,y in x.items():
                if isinstance(y,str) and ('url' in k.lower() or 'atp' in k.lower() or 'match_id' in k.lower()):
                    a=native_key(y)
                    if a:keys.add(a)
                elif isinstance(y,(dict,list)):
                    walk(y,depth+1)
        elif isinstance(x,list):
            for y in x[:30]:walk(y,depth+1)
    walk(v)
    return keys

def source_links(zip_file):
    if hashlib.sha256(Path(zip_file).read_bytes()).hexdigest()!=EXPECTED_BRIDGE_ZIP:
        raise ValueError('FIX4_BRIDGE_SHA256_MISMATCH')
    with zipfile.ZipFile(zip_file) as z:
        if z.testzip() is not None:raise ValueError('ZIP_CRC_MISMATCH')
        return list(csv.DictReader(io.StringIO(z.read('atp_archive_hf_strict_source_bridge.csv').decode('utf-8'))))

def scan(bridge_zip,history_dir):
    import pyarrow.parquet as pq
    source=source_links(bridge_zip)
    index=collections.defaultdict(list)
    for row in source:
        k=row['atp_tour_native_key']
        if not re.fullmatch(r'\d{4}/\d+/[a-z0-9]+',k):raise ValueError('SOURCE_INVALID_NATIVE_KEY')
        index[k].append(row)
    if any(len(v)!=1 for v in index.values()):raise ValueError('DUPLICATE_SOURCE_OFFICIAL_EVENT')
    base=Path(history_dir)
    manifest=base/'history_manifest.json'; bundle=base/'_tbt_bundle_manifest.json'
    mi=json.loads(manifest.read_text()); bm=json.loads(bundle.read_text())
    if not isinstance(mi.get('years'),dict) or not isinstance(bm.get('files'),dict):raise ValueError('BAD_CDB_BUNDLE_MANIFEST')
    counts=collections.Counter(); direct=collections.defaultdict(list)
    for yr in range(2015,2026):
        rec=mi['years'].get(str(yr))
        if not rec:raise ValueError(f'CDB_PARTITION_MISSING_{yr}')
        p=base/f'history-{yr}.parquet'
        expected=bm['files'].get(p.name,{}).get('sha256')
        if not expected or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError(f'CDB_PARTITION_SHA_MISMATCH_{yr}')
        # Do not read or print personal-level rows.
        df=pq.read_table(p,columns=['match_id','tour','player1_id','player2_id','player1_name','player2_name','winner_id','provider_context_json','stats_json']).to_pylist()
        counts['canonical_rows_2015_2025']+=len(df)
        for row in df:
            if str(row.get('tour') or '').lower()!='atp':continue
            counts['canonical_atp_rows']+=1
            ks=official_keys_from_context(row.get('provider_context_json'))
            native=native_key(str(row.get('match_id') or ''))
            if native:ks.add(native)
            if not ks:continue
            counts['canonical_atp_rows_with_official_native_key']+=1
            if len(ks)!=1:
                counts['canonical_conflicting_native_keys']+=1;continue
            key=next(iter(ks))
            if key not in index:continue
            counts['source_official_key_overlap_rows']+=1
            direct[key].append(row)
    # Same-event native official URL is necessary, not sufficient for player
    # identity: names + provider IDs and event date still require witnesses.
    for key,rows in direct.items():
        if len(rows)!=1:
            counts['ambiguous_multiple_canonical_event_targets']+=1;continue
        row=rows[0]; src=index[key][0]
        if len({str(row['player1_id']),str(row['player2_id'])})!=2:
            counts['incomplete_canonical_player_ids']+=1;continue
        winner=str(row.get('winner_id') or '')
        if winner not in {str(row['player1_id']),str(row['player2_id'])}:
            counts['no_completed_canonical_winner']+=1;continue
        # No name similarity can certify source ATP player ID -> canonical ID.
        counts['direct_official_key_and_completed_event_research_only']+=1
    return {
      'state':'READ_ONLY_FIX4_CANONICAL_NATIVE_OVERLAP_AUDIT',
      'source_sha256':EXPECTED_BRIDGE_ZIP,
      'cdb_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
      'source_strict_link_rows':len(source),
      'counts':dict(sorted(counts.items())),
      'canonical_write_approved':0,
      'cdb_cells_written':0,
      'provider_requests':0,
      'model_changed':False,
      'next_gate':'independently verify original ATP event date, source and canonical two player IDs, winner and full score; check current NULLs under global writer lock, backup, CAS/readback',
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--bridge-zip',required=True,type=Path)
    ap.add_argument('--cdb-dir',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    a=ap.parse_args()
    r=scan(a.bridge_zip,a.cdb_dir)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print('FIX4_CDB_NATIVE_AUDIT',json.dumps({'state':r['state'],'counts':r['counts'],'canonical_write_approved':0}))
if __name__=='__main__':main()