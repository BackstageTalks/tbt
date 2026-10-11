#!/usr/bin/env python3
"""Public-runner private Drive audit guard (no source data/credentials in stdout).

Only local safety/checkpoint validation. Publication goes to a verified PRIVATE
tbt-data release, never to public artifacts or an Actions cache.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

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
    """Store the complete SQLite cache compressed, with both byte hashes.

    GitHub Release assets are bounded; the former 1 GiB *raw* SQLite guard
    failed on otherwise successful audit runs. No cache rows are omitted.
    """
    safe_id(folder_id)
    if not cache_file.is_file() or cache_file.stat().st_size <= 0:
        raise ValueError('No completed audit cache to persist')
    output.mkdir(parents=True, exist_ok=True)
    data_copy = output / 'audit.sqlite.gz'
    with cache_file.open('rb') as original, data_copy.open('wb') as destination:
        with gzip.GzipFile(filename='', fileobj=destination, mode='wb',
                           compresslevel=6, mtime=0) as packed:
            shutil.copyfileobj(original, packed, length=1024 * 1024)
    manifest = {
        'schema': 2,
        'folder_id': folder_id,
        'source_audit_code_sha256': digest(code_file),
        'checkpoint_file': data_copy.name,
        'checkpoint_sha256': digest(data_copy),
        'checkpoint_bytes': data_copy.stat().st_size,
        'uncompressed_checkpoint_sha256': digest(cache_file),
        'uncompressed_checkpoint_bytes': cache_file.stat().st_size,
    }
    (output / 'checkpoint.json').write_text(
        json.dumps(manifest, sort_keys=True) + '\\n', encoding='utf-8')


def restore_checkpoint(source: Path, code_file: Path, folder_id: str, dest: Path) -> bool:
    """Validate private byte/code/root binding before atomic decompression.

    Schema 1 remains readable for previously published .sqlite checkpoints.
    A corrupt gzip or mismatched raw checksum never replaces the destination.
    """
    safe_id(folder_id)
    meta = source / 'checkpoint.json'
    if not meta.is_file():
        return False
    try:
        manifest = json.loads(meta.read_text(encoding='utf-8'))
        schema = manifest.get('schema')
        if schema not in (1, 2):
            return False
        if (manifest.get('folder_id') != folder_id or
            manifest.get('source_audit_code_sha256') != digest(code_file)):
            return False
        filename = 'audit.sqlite.gz' if schema == 2 else 'audit.sqlite'
        if schema == 2 and manifest.get('checkpoint_file') != filename:
            return False
        blob = source / filename
        if (not blob.is_file() or
            manifest.get('checkpoint_bytes') != blob.stat().st_size or
            manifest.get('checkpoint_sha256') != digest(blob)):
            return False
        if schema == 1:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, dest)
            return True
        limit = manifest.get('uncompressed_checkpoint_bytes')
        expected = manifest.get('uncompressed_checkpoint_sha256')
        if (type(limit) is not int or limit <= 0 or limit > 20 * 1024**3 or
            not isinstance(expected, str) or
            not re.fullmatch(r'[0-9a-f]{64}', expected)):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.drive-cdb-cache-', dir=dest.parent)
        temp_path = Path(temporary)
        try:
            total = 0
            digest_raw = hashlib.sha256()
            with os.fdopen(fd, 'wb') as target, gzip.open(blob, 'rb') as packed:
                for chunk in iter(lambda: packed.read(1024 * 1024), b''):
                    total += len(chunk)
                    if total > limit:
                        return False
                    digest_raw.update(chunk)
                    target.write(chunk)
            if total != limit or digest_raw.hexdigest() != expected:
                return False
            os.replace(temp_path, dest)
            return True
        finally:
            temp_path.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, EOFError, json.JSONDecodeError):
        return False


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
