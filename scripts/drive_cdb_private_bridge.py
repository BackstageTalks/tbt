#!/usr/bin/env python3
"""Public-runner private Drive audit guard (no source data/credentials in stdout).

Only local safety/checkpoint validation. Publication goes to a verified PRIVATE
tbt-data release, never to public artifacts or an Actions cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

CHECKPOINT_SCHEMA = 1
REQUIRED_FILES = (
    'drive-inventory.json', 'files.json', 'candidate-fields.jsonl', 'report.json',
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_id(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,128}', value):
        raise ValueError('Invalid Drive folder ID')
    return value


def validate(report_dir: Path, folder_id: str) -> dict:
    safe_id(folder_id)
    if not all((report_dir / f).is_file() for f in REQUIRED_FILES):
        raise ValueError('Incomplete private audit report')
    report = json.loads((report_dir / 'report.json').read_text(encoding='utf-8'))
    if (report.get('scope_folder_id') != folder_id or
        report.get('inventory_complete') is not True or
        int(report.get('inventory_files', 0)) <= 0 or
        int(report.get('canonical_rows', 0)) <= 0 or
        report.get('approved_fields') != 0 or
        report.get('cdb_writes') != 0 or
        report.get('all_data_importability_assessed') is not False):
        raise ValueError('Private audit safety/identity/inventory gate failed')
    partitions = report.get('canonical_partition_sha256')
    if not isinstance(partitions, dict) or len(partitions) < 70 or not all(
        re.fullmatch(r'history-\d{4}\.parquet', name) and
        re.fullmatch(r'[0-9a-f]{64}', sha) for name, sha in partitions.items()
    ):
        raise ValueError('CDB canonical snapshot pinning invalid')
    if not isinstance(report.get('comparison'), dict):
        raise ValueError('Missing actual CDB comparison')
    inventory = json.loads((report_dir / 'drive-inventory.json').read_text(encoding='utf-8'))
    files = json.loads((report_dir / 'files.json').read_text(encoding='utf-8'))
    if (not isinstance(inventory, list) or not isinstance(files, list) or
        len(inventory) != report['inventory_files'] or len(files) != len(inventory)):
        raise ValueError('Partial or inconsistent source inventory')
    for line in (report_dir / 'candidate-fields.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get('import_ready') is not False:
                raise ValueError('Report contains prematurely import-ready candidate')
    return report


def write_checkpoint(cache_file: Path, code_file: Path, folder_id: str, output: Path) -> None:
    safe_id(folder_id)
    if not cache_file.is_file() or cache_file.stat().st_size <= 0:
        raise ValueError('No completed audit cache to persist')
    output.mkdir(parents=True, exist_ok=True)
    data_copy = output / 'audit.sqlite'
    shutil.copyfile(cache_file, data_copy)
    manifest = {
        'schema': CHECKPOINT_SCHEMA,
        'folder_id': folder_id,
        'source_audit_code_sha256': digest(code_file),
        'checkpoint_sha256': digest(data_copy),
        'checkpoint_bytes': data_copy.stat().st_size,
    }
    (output / 'checkpoint.json').write_text(json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')


def restore_checkpoint(source: Path, code_file: Path, folder_id: str, dest: Path) -> bool:
    safe_id(folder_id)
    meta = source / 'checkpoint.json'
    blob = source / 'audit.sqlite'
    if not (meta.is_file() and blob.is_file()):
        return False
    try:
        manifest = json.loads(meta.read_text(encoding='utf-8'))
        if (manifest.get('schema') != CHECKPOINT_SCHEMA or
            manifest.get('folder_id') != folder_id or
            manifest.get('source_audit_code_sha256') != digest(code_file) or
            manifest.get('checkpoint_bytes') != blob.stat().st_size or
            manifest.get('checkpoint_sha256') != digest(blob)):
            return False
    except (OSError, ValueError, TypeError):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(blob, dest)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    check = sub.add_parser('validate')
    check.add_argument('--report-dir', type=Path, required=True)
    check.add_argument('--folder-id', required=True)
    for mode in ('write-checkpoint', 'restore-checkpoint'):
        p = sub.add_parser(mode)
        p.add_argument('--folder-id', required=True)
        p.add_argument('--code-file', type=Path, required=True)
        if mode == 'write-checkpoint':
            p.add_argument('--cache-file', type=Path, required=True)
            p.add_argument('--output', type=Path, required=True)
        else:
            p.add_argument('--source', type=Path, required=True)
            p.add_argument('--dest', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'validate':
        validate(args.report_dir, args.folder_id)
        print('PRIVATE_AUDIT_SAFETY_GATES_PASS')
    elif args.mode == 'write-checkpoint':
        write_checkpoint(args.cache_file, args.code_file, args.folder_id, args.output)
        print('PRIVATE_CHECKPOINT_PREPARED')
    else:
        ok = restore_checkpoint(args.source, args.code_file, args.folder_id, args.dest)
        print('PRIVATE_CHECKPOINT_VERIFIED' if ok else 'PRIVATE_CHECKPOINT_IGNORED')
        if not ok:
            raise SystemExit(2)


if __name__ == '__main__':
    main()
