#!/usr/bin/env python3
"""One-way, fail-closed CDB -> secondary DIL refresh in a private operator environment.

Never writes CDB, replaces production config, starts training, or exposes match
rows to public artifacts. An optional pointer activation affects ONLY the
secondary DIL output folder, after a full immutable-source parity audit.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

import audit_dil_cdb_secondary_parity as parity
import build_current_cdb_compare as exporter
import finalize_dil_from_cdb_v2 as importer

REPOSITORY = 'BackstageTalks/tbt-data'
TAG = 'tbt-data-v1'


def gh(*args):
    try:
        res = subprocess.run(['gh', *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError('Authorized GitHub CLI is required on the private operator machine') from exc
    if res.returncode:
        # Do not echo shell stderr; GH may include private remote URLs or credentials.
        raise RuntimeError('Authenticated private GitHub command failed')
    return res.stdout


def snapshot_metadata():
    r = json.loads(gh('api', f'repos/{REPOSITORY}/releases/tags/{TAG}'))
    return r


def relevant_receipt(release):
    return exporter.release_assets(release)


def download_full_release(folder, before):
    folder.mkdir(parents=True, exist_ok=False)
    args = ('release','download',TAG,'-R',REPOSITORY,
            '-p','history-*.parquet','-p','history_manifest.json',
            '-p','_tbt_bundle_manifest.json','-D',str(folder))
    gh(*args)
    second = snapshot_metadata()
    if relevant_receipt(before) != relevant_receipt(second):
        raise ValueError('CDB release moved during download; fail closed')
    exporter.validate_sources(folder,before,second,expected_parts=78)
    return second


@contextmanager
def local_lock(root):
    """Single-writer lock for a secondary directory; never locks canonical CDB."""
    import fcntl
    root.mkdir(parents=True,exist_ok=True)
    lockfile = root / '.dil-secondary-update.lock'
    with lockfile.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def activate_secondary_pointer(folder, artifact, report):
    """Atomic local pointer update; not a service config or CDB operation."""
    folder=Path(folder).resolve();artifact=Path(artifact).resolve()
    if artifact.parent != folder or not artifact.is_file():
        raise ValueError('Refuse pointer outside dedicated secondary output directory')
    if report.get('status') != 'VERIFIED_CURRENT_CDB_PARITY':
        raise ValueError('Current parity must be 100% before activating secondary pointer')
    target = folder/'current-secondary.json'
    before=folder/'previous-secondary.json'
    if target.exists():
        prior=json.loads(target.read_text(encoding='utf-8'))
        previous_file=folder/prior['filename']
        if previous_file.parent != folder or not previous_file.is_file():
            raise ValueError('Existing secondary pointer is invalid')
        temp_backup=folder/'.previous-secondary.json.tmp'
        if temp_backup.exists():raise FileExistsError('Unfinished previous secondary swap')
        temp_backup.write_text(json.dumps(prior,indent=2,sort_keys=True)+'\n')
        os.replace(temp_backup,before)
    body={'schema':'DIL_SECONDARY_POINTER_V1',
          'filename':artifact.name,
          'source_release_manifest_sha256':report['source_release_manifest_sha256'],
          'source_cdb_sha256':report['source_cdb_sha256'],
          'secondary_only':True,
          'production_cdb_modified':False,
          'production_database_switch':False}
    temp=folder/'.current-secondary.json.tmp'
    if temp.exists():raise FileExistsError('Unfinished secondary pointer update')
    temp.write_text(json.dumps(body,indent=2,sort_keys=True)+'\n')
    os.replace(temp,target)
    check=json.loads(target.read_text(encoding='utf-8'))
    if check != body:raise AssertionError('Secondary pointer readback mismatch')
    return check


def refresh(base_dil, work_dir, secondary_dir, *, activate=False):
    work_dir=Path(work_dir).resolve()
    secondary_dir=Path(secondary_dir).resolve()
    if base_dil is None:
        pointer=secondary_dir/'current-secondary.json'
        if not pointer.is_file():
            raise FileNotFoundError('Pass --base-dil for the first import; no active secondary pointer exists')
        record=json.loads(pointer.read_text(encoding='utf-8'))
        name=record.get('filename')
        if not isinstance(name,str) or Path(name).name!=name or not record.get('secondary_only'):
            raise ValueError('Invalid active secondary pointer')
        base_dil=secondary_dir/name
    base_dil=Path(base_dil).resolve()
    if not base_dil.is_file():raise FileNotFoundError('Immutable input DIL snapshot is missing')
    if secondary_dir == work_dir or secondary_dir in work_dir.parents or work_dir in secondary_dir.parents:
        raise ValueError('Work and secondary release directories must be separate')
    if base_dil.parent == work_dir:
        raise ValueError('Input DIL must be outside the scratch directory')
    with local_lock(secondary_dir):
        if work_dir.exists():raise FileExistsError('Use a fresh, empty private work directory')
        work_dir.mkdir(parents=True)
        before=snapshot_metadata()
        (work_dir/'release-before.json').write_text(json.dumps(before)+'\n')
        after=download_full_release(work_dir/'cdb-release',before)
        (work_dir/'release-after.json').write_text(json.dumps(after)+'\n')
        cdb_file=work_dir/'cdb-compare.sqlite'
        export_receipt=exporter.build(work_dir/'cdb-release',work_dir/'release-before.json',
                    work_dir/'release-after.json',cdb_file)
        source_sha=export_receipt['export_sqlite_sha256']
        release_sha=export_receipt['source_release_manifest_sha256']
        staged=work_dir/'staged-secondary.sqlite'
        result=importer.reconcile(base_dil,cdb_file,staged,source_sha,release_sha,
                                  quick_check=True, export_receipt=Path(str(cdb_file)+'.receipt.json'))
        audit=parity.audit(cdb_file,staged,source_sha,full_integrity=True,
                           attest=Path(str(cdb_file)+'.receipt.json'))
        (work_dir/'secondary-parity.json').write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n')
        if not audit['secondary_promotion_allowed'] or result['data_gate'] != 'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION':
            # Keep failing report in private scratch, never affect current secondary.
            raise ValueError('Secondary DATA PARITY BLOCKED: review private scratch audit')
        # Catch a concurrent CDB release mutation AFTER all long-running checks.
        latest=snapshot_metadata()
        if relevant_receipt(before)!=relevant_receipt(latest):
            raise ValueError('CANONICAL RELEASE CHANGED DURING QUALITY GATE; refusing secondary activation')
        # Release files are immutable and versioned by CDB manifest hash and DIL content hash.
        name=f'DIL_SECONDARY_{release_sha[:16]}_{result["result_dil_sha256"][:16]}.sqlite'
        published=secondary_dir/name
        if published.exists():raise FileExistsError('Version already exists; preserve immutable release')
        os.replace(staged,published)
        # Independently re-read published bytes before changing any active pointer.
        if importer.sha256(published) != result['result_dil_sha256']:
            raise ValueError('Published secondary SQLite SHA readback mismatch')
        importer_receipt=Path(str(staged)+'.audit.json')
        if not importer_receipt.is_file():
            raise ValueError('Missing immutable importer audit receipt')
        preserved_receipt=secondary_dir/(name+'.import.json')
        if preserved_receipt.exists():raise FileExistsError('Importer audit already exists')
        shutil.copyfile(importer_receipt,preserved_receipt)
        if parity.file_sha256(importer_receipt)!=parity.file_sha256(preserved_receipt):
            raise ValueError('Importer audit readback mismatch')
        audit_path=secondary_dir/(name+'.parity.json')
        if audit_path.exists():raise FileExistsError('Secondary parity report already exists')
        audit_path.write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n')
        if activate:
            activate_secondary_pointer(secondary_dir,published,audit)
        return {'status':'SECONDARY_ACTIVATED_VERIFIED' if activate else 'SECONDARY_SNAPSHOT_VERIFIED_NOT_ACTIVATED',
                'secondary_artifact':str(published),
                'importer_report':str(preserved_receipt),
                'parity_report':str(audit_path),
                'cdb_release_manifest_sha256':release_sha,
                'cdb_mutated':False,'production_switched':False,'model_training':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-dil',default=None,help='Initial import source; omit later to use current secondary pointer')
    p.add_argument('--work-dir',required=True,help='New empty private scratch folder; requires ample disk')
    p.add_argument('--secondary-dir',required=True,help='Private folder for versioned secondary DIL only')
    p.add_argument('--activate-secondary',action='store_true',help='Atomic update of a local secondary-only JSON pointer')
    args=p.parse_args()
    try:
        report=refresh(args.base_dil,args.work_dir,args.secondary_dir,activate=args.activate_secondary)
        print(json.dumps(report,sort_keys=True))
    except Exception as exc:
        print('BLOCKED: '+str(exc),file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':sys.exit(main())