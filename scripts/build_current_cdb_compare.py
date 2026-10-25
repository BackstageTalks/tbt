#!/usr/bin/env python3
"""Convert a SHA-pinned full canonical CDB history release to read-only comparison SQLite.

Run inside BackstageTalks/tbt repo environment; uses its existing canonical
history_snapshot loader/validation. Only writes a separate isolated SQLite
export. Never writes CDB, DIL production, or model. Requires before/after
release metadata proving a stable release throughout source acquisition.
"""
from __future__ import annotations
import argparse, collections, datetime as dt, hashlib, json, os, pathlib, re, sqlite3, sys

FIELDS = ['match_id','tour','scheduled_at','player1_id','player1_name','player2_id','player2_name',
    'surface','tournament','tournament_id','tournament_level','round_name',
    'player1_rank','player2_rank','winner_id','status','best_of','indoor',
    'stats_json','provider_context_json','source_year']
SCHEMA='''CREATE TABLE cdb_matches (
 match_id TEXT NOT NULL PRIMARY KEY, tour TEXT, scheduled_at INTEGER,
 player1_id TEXT, player1_name TEXT, player2_id TEXT, player2_name TEXT,
 surface TEXT, tournament TEXT, tournament_id TEXT, tournament_level TEXT,
 round_name TEXT, player1_rank REAL, player2_rank REAL, winner_id TEXT,
 status TEXT, best_of REAL, indoor INTEGER, stats_json TEXT,
 provider_context_json TEXT, source_year INTEGER NOT NULL
) WITHOUT ROWID'''

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(8*1024*1024),b''):h.update(part)
    return h.hexdigest()

def release_assets(release):
    if release.get('tag_name')!='tbt-data-v1':raise ValueError('Wrong CDB release tag')
    assets={}
    for a in release.get('assets',[]):
        name=a['name'];digest=a.get('digest','')
        if name in assets:raise ValueError('Duplicate release asset')
        if name=='history_manifest.json' or name=='_tbt_bundle_manifest.json' or re.fullmatch(r'history-\d{4}\.parquet',name):
            if not re.fullmatch('sha256:[a-f0-9]{64}',digest):raise ValueError('Missing SHA for '+name)
            assets[name]={'id':a.get('id'),'digest':digest[7:],'size':int(a['size'])}
    return assets

def validate_sources(folder,before,after,expected_parts=78):
    folder=pathlib.Path(folder)
    first,second=release_assets(before),release_assets(after)
    if first!=second:raise ValueError('RELEASE_MOVED_DURING_DOWNLOAD')
    manifestfile=folder/'history_manifest.json'
    manifest=json.loads(manifestfile.read_text())
    years=manifest.get('years')
    if not isinstance(years,dict) or len(years)!=expected_parts:
        raise ValueError('CDB YEAR PARTITION SET INCOMPLETE')
    partnames={f'history-{int(y):04d}.parquet' for y in years}
    allneeded=partnames|{'history_manifest.json','_tbt_bundle_manifest.json'}
    if not allneeded.issubset(first):raise ValueError('CDB RELEASE ASSETS MISSING')
    bundle=json.loads((folder/'_tbt_bundle_manifest.json').read_text())
    bf=bundle.get('files',{})
    if not isinstance(bf,dict):raise ValueError('CDB BUNDLE MANIFEST MISSING FILE MAP')
    totals=0
    for name in sorted(allneeded):
        file=folder/name
        if not file.is_file() or file.stat().st_size!=first[name]['size']:
            raise ValueError('CDB SOURCE LENGTH MISMATCH: '+name)
        digest=sha256(file)
        if digest!=first[name]['digest']:
            raise ValueError('CDB RELEASE DIGEST MISMATCH: '+name)
        if name=='_tbt_bundle_manifest.json':continue # Self-hash is not a bundle entry.
        if bf.get(name,{}).get('sha256')!=digest:
            raise ValueError('CDB BUNDLE FILE DIGEST MISMATCH: '+name)
        if name.endswith('.parquet'):
            year=str(int(name[len('history-'):-len('.parquet')]))
            if years[year].get('sha256')!=digest:raise ValueError('CDB YEAR MANIFEST DIGEST MISMATCH: '+name)
            with file.open('rb') as f:
                if f.read(4)!=b'PAR1':raise ValueError('Not Parquet: '+name)
                f.seek(-4,os.SEEK_END)
                if f.read(4)!=b'PAR1':raise ValueError('Not Parquet trailer: '+name)
        totals+=first[name]['size']
    if any(x.name.startswith('history-') and x.suffix=='.parquet' and x.name not in partnames for x in folder.iterdir()):
        raise ValueError('Unlisted partition: fail closed')
    return {'year_count':len(years),'years':sorted(map(int,years)),
            'release_manifest_sha256':first['history_manifest.json']['digest'],
            'bundle_manifest_sha256':first['_tbt_bundle_manifest.json']['digest'],
            'release_part_bytes':totals,'pinned_assets':first}

def write_rows(db, rows, expected_year):
    count=0
    columns=','.join('"'+x+'"' for x in FIELDS)
    vals=','.join('?'*len(FIELDS))
    sql='INSERT INTO cdb_matches ('+columns+') VALUES ('+vals+')'
    for r in rows:
        if set(FIELDS)-set(r):raise ValueError('Missing CDB export fields: '+repr(set(FIELDS)-set(r)))
        if int(r['source_year'])!=int(expected_year):raise ValueError('Wrong CDB partition year')
        if not isinstance(r['scheduled_at'],int):raise ValueError('CDB export timestamp must be seconds')
        if not r['match_id'] or not r['player1_id'] or not r['player2_id']:
            raise ValueError('Incomplete canonical CDB identity')
        try:
            ts=dt.datetime.fromtimestamp(r['scheduled_at'],dt.timezone.utc)
        except (ValueError,OverflowError,OSError):raise ValueError('Invalid CDB timestamp')
        if ts.year!=int(expected_year):raise ValueError('Date/partition disagreement')
        if not isinstance(json.loads(r['stats_json']),dict):raise ValueError('Nonobject CDB stats')
        db.execute(sql,tuple(r[x] for x in FIELDS))
        count+=1
    return count

def rows_from_canonical(matches,year):
    # This repository module already performs strict JSON and rate-stat checks.
    from tbt.data.history_snapshot import _record_to_row
    for m in matches:
        row=_record_to_row(m)
        ts=row['scheduled_at']
        if not isinstance(ts,dt.datetime):raise ValueError('Invalid UTC canonical scheduled_at')
        row['scheduled_at']=int(ts.timestamp()) # signed Unix seconds (not nanoseconds)
        row['source_year']=year
        yield row

def build(folder, before_file, after_file, output, expected_parts=78):
    folder=pathlib.Path(folder).resolve(); output=pathlib.Path(output).resolve()
    if output.exists() or pathlib.Path(str(output)+'.receipt.json').exists():raise FileExistsError('Refusing to overwrite comparison export')
    before=json.loads(pathlib.Path(before_file).read_text())
    after=json.loads(pathlib.Path(after_file).read_text())
    attestation=validate_sources(folder,before,after,expected_parts)
    # Defer dependency until after complete source receipts are validated.
    from tbt.data.history_snapshot import load_partitions
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=pathlib.Path(str(output)+'.incomplete')
    if temp.exists():raise FileExistsError('Refusing to overwrite prior partial export')
    db=sqlite3.connect(str(temp))
    count=0;year_count={}
    try:
        db.execute(SCHEMA)
        for year in attestation['years']:
            data=load_partitions(folder,years=[year])
            # Data is from canonical CDB loader; duplicates abort rather than merge silently.
            n=write_rows(db,rows_from_canonical(data,year),year)
            year_count[str(year)]=n; count+=n
            db.commit()
        if count<1 or db.execute('SELECT COUNT(*) FROM cdb_matches').fetchone()[0]!=count:
            raise ValueError('CDB export read-back count mismatch')
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('CDB export quick_check failure')
        db.close();db=None
        # Assert source still matches the same 78 release asset digests after export.
        last=validate_sources(folder,before,after,expected_parts)
        if last!=attestation:raise ValueError('CDB source changed during export')
        export_sha=sha256(temp)
        temp.replace(output)
        report={'schema':'BLINQ_FULL_CDB_COMPARE_EXPORT_V2','status':'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY',
           'source_release':'BackstageTalks/tbt-data/tbt-data-v1',
           'source_release_manifest_sha256':attestation['release_manifest_sha256'],
           'source_bundle_manifest_sha256':attestation['bundle_manifest_sha256'],
           'source_partition_count':len(year_count),'source_rows_by_year':year_count,
           'source_matches':count,'export_sqlite_sha256':export_sha,
           'export_sqlite_bytes':output.stat().st_size,
           'export_timestamp_unit':'UTC unix seconds',
           'cdb_mutated':False,'DIL_mutated':False,'training_eligible':False,
           'publication_authorized':False}
        pathlib.Path(str(output)+'.receipt.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
        return report
    except BaseException:
        if db is not None:db.close()
        temp.unlink(missing_ok=True)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for x in ('history-dir','release-before','release-after','out'):
        p.add_argument('--'+x,required=True)
    a=p.parse_args()
    try:res=build(a.history_dir,a.release_before,a.release_after,a.out)
    except Exception as e:print('BLOCKED: '+str(e),file=sys.stderr);return 2
    print(json.dumps(res,sort_keys=True));return 0

if __name__=='__main__':sys.exit(main())