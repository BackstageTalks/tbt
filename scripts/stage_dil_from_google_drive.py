#!/usr/bin/env python3
"""Restore an immutable private secondary DIL source from a SHA-pinned Drive folder.

Requires BLINQ_DRIVE_READER_JSON for the existing project service-account READER.
No Drive writes, no canonical CDB writes, no serving change or model training.
Follow with refresh_dil_secondary.py only on an authorized, private Linux/WSL SSD.
"""
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,re,shutil,sqlite3,subprocess,sys,tempfile

SCHEMA='DIL_PRIVATE_ARCHIVE_CHUNKS_20261025_V1'
DRIVE='https://www.googleapis.com/drive/v3/files'
HEX=re.compile(r'^[0-9a-f]{64}$')
NAME=re.compile(r'^part\d{3}\.bin$')

def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def checked_manifest(text):
 m=json.loads(text) if isinstance(text,(bytes,str)) else text
 if not isinstance(m,dict) or m.get('schema')!=SCHEMA:raise ValueError('Unverified DIL part manifest schema')
 parts=m.get('parts')
 if not isinstance(parts,list) or not (1<=len(parts)<=2048):raise ValueError('Bad archive part count')
 expected=[f'part{i:03d}.bin' for i in range(1,len(parts)+1)]
 if [v.get('filename') if isinstance(v,dict) else None for v in parts]!=expected:
  raise ValueError('Missing, duplicate or out-of-order part names')
 for p in parts:
  if not NAME.fullmatch(p['filename']) or not isinstance(p.get('size'),int) or not (0<p['size']<=20*1024*1024) or not HEX.fullmatch(str(p.get('sha256'))):
   raise ValueError('Bad archive part contract')
 for key in ('archive_sha256','unpacked_sqlite_sha256'):
  if not HEX.fullmatch(str(m.get(key))):raise ValueError('Invalid pinned snapshot SHA')
 if sum(x['size'] for x in parts)<1 or not isinstance(m.get('unpacked_sqlite_bytes'),int) or m['unpacked_sqlite_bytes']<1:
  raise ValueError('Incomplete SQLite byte attestation')
 return m

def reconstruct(folder, m, out, *, full_integrity=True):
 root=pathlib.Path(folder).resolve();out=pathlib.Path(out).resolve()
 if out.exists() or pathlib.Path(str(out)+'.restore.json').exists():raise FileExistsError('Refuse to overwrite existing immutable DIL')
 if out.parent==root or root in out.parents:raise ValueError('Output must be outside private temporary source directory')
 out.parent.mkdir(parents=True,exist_ok=True)
 archive=out.with_name(out.name+'.archive.partial.zst');sql=out.with_name(out.name+'.incomplete')
 if archive.exists() or sql.exists():raise FileExistsError('Unfinished restoration already exists')
 try:
  checksum=hashlib.sha256()
  with archive.open('wb') as dst:
   for part in m['parts']:
    path=root/part['filename']
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=part['size'] or sha(path)!=part['sha256']:
     raise ValueError('Archive source part verification failed: '+part['filename'])
    with path.open('rb') as fd:
     for block in iter(lambda:fd.read(4*1024*1024),b''):
      checksum.update(block);dst.write(block)
  if checksum.hexdigest()!=m['archive_sha256']:
   raise ValueError('Concatenated compressed archive hash mismatch')
  try:subprocess.run(['zstd','-d','-q','-f','-o',str(sql),str(archive)],check=True,stderr=subprocess.DEVNULL,stdout=subprocess.DEVNULL)
  except (subprocess.CalledProcessError,FileNotFoundError) as e:raise RuntimeError('zstd verified decompression failed') from e
  if sql.stat().st_size!=m['unpacked_sqlite_bytes'] or sha(sql)!=m['unpacked_sqlite_sha256']:
   raise ValueError('DIL restored database SHA-256/length mismatch')
  db=sqlite3.connect(sql.as_uri()+'?mode=ro&immutable=1',uri=True)
  try:
   qc=db.execute('PRAGMA integrity_check' if full_integrity else 'PRAGMA quick_check').fetchall()
   if qc!=[('ok',)]:raise ValueError('Restored DIL SQLite integrity failure')
   rows=db.execute('SELECT COUNT(*) FROM canonical_matches').fetchone()[0]
   if rows<1:raise ValueError('Empty restored canonical matches')
  finally:db.close()
  sql.replace(out)
  receipt={'schema':'DIL_RESTORED_PRIVATE_DRIVE_SNAPSHOT_V1','status':'VERIFIED_ISOLATED_RESTORE_NOT_PRODUCTION',
           'canonical_matches':rows,'sqlite_sha256':m['unpacked_sqlite_sha256'],
           'compressed_archive_sha256':m['archive_sha256'], 'parts_verified':len(m['parts']),
           'full_integrity_check':full_integrity,
           'cdb_modified':False,'production_activated':False,'training_changed':False}
  pathlib.Path(str(out)+'.restore.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
  return receipt
 except BaseException:
  sql.unlink(missing_ok=True)
  raise
 finally:archive.unlink(missing_ok=True)

def make_session():
 secret=os.environ.get('BLINQ_DRIVE_READER_JSON')
 if not secret:raise RuntimeError('Existing authorized private Drive service-account secret is required')
 from google.oauth2 import service_account
 from google.auth.transport.requests import AuthorizedSession
 info=json.loads(secret)
 if info.get('type')!='service_account':raise ValueError('Expected private service account credential')
 creds=service_account.Credentials.from_service_account_info(info,scopes=['https://www.googleapis.com/auth/drive.readonly'])
 return AuthorizedSession(creds)

def stage_drive(folder_id, destination, download_dir, *, session=None, expected_archive_sha256=None, expected_sqlite_sha256=None):
 if not re.fullmatch('[A-Za-z0-9_-]{15,150}',folder_id):raise ValueError('Invalid private Drive folder ID')
 folder=pathlib.Path(download_dir).resolve()
 if folder.exists():raise FileExistsError('Private scratch must not exist before run')
 s=session or make_session()
 folder.mkdir(parents=True)
 try:
  files={};token=None
  while True:
   params={'q':f"'{folder_id}' in parents and trashed = false",'fields':'nextPageToken,files(id,name,size,mimeType)',
           'pageSize':1000,'supportsAllDrives':'true','includeItemsFromAllDrives':'true'}
   if token:params['pageToken']=token
   response=s.get(DRIVE,params=params,timeout=90);response.raise_for_status();payload=response.json()
   for f in payload.get('files',[]):
    if f.get('name') in files:raise ValueError('Duplicate Drive file name')
    files[f.get('name')]=f
   token=payload.get('nextPageToken')
   if not token:break
  meta=files.get('archive_parts_manifest.json')
  if not meta or not meta.get('id'):raise FileNotFoundError('Private Drive archive manifest unavailable')
  m=checked_manifest(_fetch_bytes(s,meta['id'],limit=128*1024))
  if expected_archive_sha256 is not None and m['archive_sha256'] != expected_archive_sha256:
   raise ValueError('Private Drive archive differs from independently pinned digest')
  if expected_sqlite_sha256 is not None and m['unpacked_sqlite_sha256'] != expected_sqlite_sha256:
   raise ValueError('Private DIL SQLite differs from independently pinned digest')
  wanted={'archive_parts_manifest.json'}|{x['filename'] for x in m['parts']}
  if not wanted.issubset(files):raise FileNotFoundError('Private service reader cannot see all immutable DIL parts')
  for f in m['parts']:
   remote=files[f['filename']]
   if str(remote.get('size'))!=str(f['size']):raise ValueError('Private Drive file length disagreement')
   _download_to(s,remote['id'],folder/f['filename'],f['size'],f['sha256'])
  return reconstruct(folder,m,destination,full_integrity=True)
 finally:
  shutil.rmtree(folder,ignore_errors=True)

def _fetch_bytes(session,file_id,*,limit):
 r=session.get(f'{DRIVE}/{file_id}',params={'alt':'media','supportsAllDrives':'true'},timeout=90,stream=True)
 r.raise_for_status();size=0;pieces=[]
 for block in r.iter_content(chunk_size=256*1024):
  if not block:continue
  size+=len(block)
  if size>limit:raise ValueError('Private Drive manifest exceeds maximum size')
  pieces.append(block)
 return b''.join(pieces)

def _download_to(session,file_id,target,size,digest):
 h=hashlib.sha256();length=0
 try:
  with session.get(f'{DRIVE}/{file_id}',params={'alt':'media','supportsAllDrives':'true'},timeout=120,stream=True) as r:
   r.raise_for_status()
   with target.open('xb') as out:
    for part in r.iter_content(chunk_size=1024*1024):
     if not part:continue
     length+=len(part)
     if length>size:raise ValueError('Oversized Drive file during download')
     h.update(part);out.write(part)
  if length!=size or h.hexdigest()!=digest:raise ValueError('Drive part size/digest mismatch')
 except BaseException:
  target.unlink(missing_ok=True)
  raise

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--folder-id',required=True)
 p.add_argument('--out',required=True,help='New destination .sqlite file on private SSD; never an existing production DB')
 p.add_argument('--scratch',required=True,help='New empty scratch folder with enough space')
 p.add_argument('--expected-archive-sha256',required=True,help='Independently checked Drive archive SHA-256')
 p.add_argument('--expected-sqlite-sha256',required=True,help='Independently checked SQLite SHA-256')
 a=p.parse_args()
 try:report=stage_drive(a.folder_id,a.out,a.scratch,expected_archive_sha256=a.expected_archive_sha256,expected_sqlite_sha256=a.expected_sqlite_sha256)
 except Exception as e:
  print('BLOCKED_PRIVATE_DIL_DRIVE_RESTORE:'+type(e).__name__,file=sys.stderr)
  return 2
 print(json.dumps(report,sort_keys=True));return 0

if __name__=='__main__':sys.exit(main())
