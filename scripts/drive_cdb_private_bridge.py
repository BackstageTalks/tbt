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


# Never put raw multi-GiB SQLite files directly into release assets.
# GitHub Release assets are capped at 2 GiB; preserve headroom for metadata.
MAX_RAW_CHECKPOINT_BYTES = 4 * 1024 ** 3
MAX_COMPRESSED_CHECKPOINT_BYTES = 1_800_000_000


def write_checkpoint(cache_file: Path, code_file: Path, folder_id: str, output: Path) -> None:
    """Emit bounded gzip checkpoint with independently verifiable raw and packed SHA."""
    safe_id(folder_id)
    if (not cache_file.is_file() or not 0 < cache_file.stat().st_size <= MAX_RAW_CHECKPOINT_BYTES):
        raise ValueError('Missing or over-limit completed audit cache')
    output.mkdir(parents=True, exist_ok=True)
    blob = output / 'audit.sqlite.gz'
    pending = output / 'audit.sqlite.gz.pending'
    raw_hash = hashlib.sha256()
    raw_bytes = 0
    try:
        with cache_file.open('rb') as source, pending.open('wb') as target:
            with gzip.GzipFile(filename='', mode='wb', fileobj=target,
                               compresslevel=1, mtime=0) as packed:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    raw_bytes += len(chunk)
                    if raw_bytes > MAX_RAW_CHECKPOINT_BYTES:
                        raise ValueError('Checkpoint grew beyond raw size limit')
                    raw_hash.update(chunk)
                    packed.write(chunk)
        if pending.stat().st_size > MAX_COMPRESSED_CHECKPOINT_BYTES:
            raise ValueError('Compressed checkpoint too large for private release')
        if (raw_bytes != cache_file.stat().st_size
                or raw_hash.hexdigest() != digest(cache_file)):
            raise ValueError('Cache changed while writing checkpoint')
        pending.replace(blob)
        manifest = {
            'schema': 2,
            'encoding': 'gzip',
            'folder_id': folder_id,
            'source_audit_code_sha256': digest(code_file),
            'checkpoint_sha256': digest(blob),
            'checkpoint_bytes': blob.stat().st_size,
            'uncompressed_sha256': raw_hash.hexdigest(),
            'uncompressed_bytes': raw_bytes,
        }
        (output / 'checkpoint.json').write_text(
            json.dumps(manifest, sort_keys=True) + '\n', encoding='utf-8')
    finally:
        pending.unlink(missing_ok=True)


def restore_checkpoint(source: Path, code_file: Path, folder_id: str, dest: Path) -> bool:
    """Accept legacy raw v1 and compressed v2, never leave a partial restored DB."""
    safe_id(folder_id)
    meta = source / 'checkpoint.json'
    if not meta.is_file():
        return False
    try:
        manifest = json.loads(meta.read_text(encoding='utf-8'))
        schema = manifest.get('schema')
        if (schema not in (1, 2) or manifest.get('folder_id') != folder_id
                or manifest.get('source_audit_code_sha256') != digest(code_file)):
            return False
        blob = source / ('audit.sqlite.gz' if schema == 2 else 'audit.sqlite')
        if not blob.is_file():
            return False
        if (manifest.get('checkpoint_bytes') != blob.stat().st_size
                or manifest.get('checkpoint_sha256') != digest(blob)):
            return False
        if schema == 1:
            if blob.stat().st_size > MAX_RAW_CHECKPOINT_BYTES:
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + '.pending')
            try:
                shutil.copyfile(blob, tmp)
                tmp.replace(dest)
            finally:
                tmp.unlink(missing_ok=True)
            return True
        if (manifest.get('encoding') != 'gzip'
                or not isinstance(manifest.get('uncompressed_bytes'), int)
                or not 0 < manifest['uncompressed_bytes'] <= MAX_RAW_CHECKPOINT_BYTES
                or not isinstance(manifest.get('uncompressed_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', manifest['uncompressed_sha256'])
                or blob.stat().st_size > MAX_COMPRESSED_CHECKPOINT_BYTES):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + '.pending')
        raw_hash = hashlib.sha256()
        total = 0
        try:
            with gzip.open(blob, 'rb') as packed, tmp.open('wb') as target:
                for chunk in iter(lambda: packed.read(1024 * 1024), b''):
                    total += len(chunk)
                    if total > MAX_RAW_CHECKPOINT_BYTES:
                        raise ValueError('Decompressed checkpoint exceeds size limit')
                    raw_hash.update(chunk)
                    target.write(chunk)
            if (total != manifest['uncompressed_bytes']
                    or raw_hash.hexdigest() != manifest['uncompressed_sha256']):
                return False
            tmp.replace(dest)
            return True
        finally:
            tmp.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, EOFError):
        return False


def verify_priority_reader_migration(legacy_code: Path, priority_code: Path) -> None:
    """Prove that the new reader retains identical cached observation semantics.

    Only a pure source-order helper, an opt-in CLI argument and the item-order
    selection may differ. Compare every other byte of the two full scripts.
    This is intentionally strict: unrelated parser edits require a new review.
    """
    old = legacy_code.read_text(encoding='utf-8')
    current = priority_code.read_text(encoding='utf-8')
    start = 'def audit_source_priority(item):\n'
    end = 'def records(stream, suffix):\n'
    if current.count(start) != 1 or current.count(end) != 1:
        raise ValueError('Expected exactly one historical-source priority helper')
    a = current.index(start)
    b = current.index(end, a)
    if not a < b:
        raise ValueError('Invalid source-priority helper bounds')
    current = current[:a] + current[b:]
    flag = (
        "    ap.add_argument('--prioritize-historical-stats', action='store_true',\n"
        "                    help='Opt in to historical match-stat sample ordering; default preserves existing checkpoint order')\n"
    )
    if current.count(flag) != 1:
        raise ValueError('Historical-priority opt-in CLI contract changed')
    current = current.replace(flag, '', 1)
    ordering = (
        '    # Keep default scanner behavior identical for pinned production checkpoints.\n'
        '    # A new priority policy needs an explicitly reviewed cache/code migration.\n'
        '    ordered = sorted(inventory, key=audit_source_priority) if args.prioritize_historical_stats else inventory\n'
        '    for item in ordered:'
    )
    if current.count(ordering) != 1:
        raise ValueError('Historical-priority loop contract changed')
    current = current.replace(ordering, '    for item in inventory:', 1)
    if not old or old != current:
        raise ValueError('Cached source parser semantics changed: cannot migrate checkpoint')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    check = sub.add_parser('validate')
    check.add_argument('--report-dir', type=Path, required=True)
    check.add_argument('--folder-id', required=True)
    migrate = sub.add_parser('verify-priority-reader')
    migrate.add_argument('--legacy-code', type=Path, required=True)
    migrate.add_argument('--priority-code', type=Path, required=True)
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
    if args.mode == 'verify-priority-reader':
        verify_priority_reader_migration(args.legacy_code, args.priority_code)
        print('PRIVATE_PRIORITY_READER_CHECKPOINT_SCHEMA_COMPATIBLE')
    elif args.mode == 'validate':
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
