#!/usr/bin/env python3
"""Read-only health and tightly guarded rollback for the PRIVATE secondary DIL.

Never changes primary CDB, production config, running models, source matches or
stats. Offline means that the last pinned snapshot is authentic, NOT that it is
fresh against the live primary. Live verification requires authenticated `gh`.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

SCHEMA = 'DIL_SECONDARY_POINTER_V1'
PARITY_SCHEMA = 'DIL_SECONDARY_STRICT_CURRENT_CDB_PARITY_V1'
IMPORT_SCHEMA = 'BLINQ_DIL_CDB_ISOLATED_RECONCILIATION_V1'
SHA = re.compile(r'^[0-9a-f]{64}$')
RELEASE_REPO = 'BackstageTalks/tbt-data'
RELEASE_TAG = 'tbt-data-v1'
PARITY_FAILURES = (
    'missing_cdb_match_ids_in_dil', 'dil_canonical_ids_not_in_cdb',
    'core_mismatched_matches', 'cdb_metadata_missing_fields',
    'cdb_metadata_conflicting_fields', 'cdb_stat_cells_missing_effective_dil',
    'cdb_stat_cells_conflicting_effective_dil', 'cdb_sqlite_check_failures',
    'dil_sqlite_check_failures', 'invalid_dil_canonical_metric_cells',
    'invalid_dil_overlay_metric_cells', 'cdb_foreign_key_failures',
    'dil_foreign_key_failures',
)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for piece in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(piece)
    return h.hexdigest()


def read_json(path: Path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Expected immutable local receipt or pointer is missing or symlinked')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('Receipt must be a JSON object')
    return result


def valid_sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def validate_snapshot(folder: Path, pointer: dict) -> dict:
    """Independently validate a pinned version and its immutable QA receipts."""
    if pointer.get('schema') != SCHEMA or pointer.get('secondary_only') is not True:
        raise ValueError('No authorized secondary pointer contract')
    if pointer.get('production_database_switch') is not False or pointer.get('production_cdb_modified') is not False:
        raise ValueError('Pointer must attest that primary and production are untouched')
    name = pointer.get('filename')
    if (not isinstance(name, str) or not name.endswith('.sqlite') or
            Path(name).name != name or name in ('.sqlite', '..sqlite')):
        raise ValueError('Invalid immutable secondary filename')
    folder = folder.resolve()
    artifact = folder / name
    if artifact.is_symlink() or artifact.resolve().parent != folder or not artifact.is_file():
        raise ValueError('Secondary SQLite artifact missing or outside private folder')
    release = pointer.get('source_release_manifest_sha256')
    cdb = pointer.get('source_cdb_sha256')
    if not valid_sha(release) or not valid_sha(cdb):
        raise ValueError('Missing primary source SHA-256 receipt')
    importer = read_json(folder / (name + '.import.json'))
    parity = read_json(folder / (name + '.parity.json'))
    if (importer.get('schema') != IMPORT_SCHEMA or
            importer.get('status') != 'ISOLATED_VERIFIED_NOT_PRODUCTION' or
            importer.get('data_gate') != 'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION' or
            importer.get('source_export_attested') is not True or
            importer.get('production_promoted') is not False or
            importer.get('cdb_modified') is not False or
            importer.get('model_untouched') is not True or
            importer.get('source_cdb_sha256') != cdb or
            importer.get('source_release_manifest_sha256') != release):
        raise ValueError('Importer receipt is not proven, source-pinned, or secondary-only')
    if (parity.get('schema') != PARITY_SCHEMA or
            parity.get('status') != 'VERIFIED_CURRENT_CDB_PARITY' or
            parity.get('secondary_promotion_allowed') is not True or
            parity.get('full_integrity_check') is not True or
            parity.get('production_cdb_modified') is not False or
            parity.get('production_cdb_replaced') is not False or
            parity.get('model_training_authorized') is not False or
            parity.get('source_cdb_sha256') != cdb or
            parity.get('source_release_manifest_sha256') != release):
        raise ValueError('Parity receipt does not attest full secondary-only CDB equality')
    counts = parity.get('counts')
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(k, 0), int) or counts.get(k, 0) != 0
        for k in PARITY_FAILURES
    ):
        raise ValueError('Parity receipt contains data, metadata or integrity failures')
    expected_matches = importer.get('canonical_matches_after')
    importer_counts = importer.get('counts')
    if (not isinstance(expected_matches, int) or expected_matches <= 0 or
            not isinstance(importer_counts, dict) or
            importer_counts.get('rows_cdb') != expected_matches or
            importer.get('quick_check') != 'ok' or
            importer.get('provenance_missing') != 0 or
            counts.get('cdb_matches') != expected_matches or
            counts.get('dil_matches') != expected_matches):
        raise ValueError('Source and target match counts do not agree in signed receipts')
    digest = file_sha256(artifact)
    if digest != importer.get('result_dil_sha256'):
        raise ValueError('Secondary artifact bytes differ from import receipt')
    # Independently read actual persisted table count (not just a JSON receipt).
    db = sqlite3.connect(artifact.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        actual_matches = db.execute('SELECT COUNT(*) FROM canonical_matches').fetchone()[0]
    finally:
        db.close()
    if actual_matches != expected_matches:
        raise ValueError('Persisted secondary canonical match count disagrees with QA')
    return {'filename': name, 'artifact_sha256': digest,
            'source_release_manifest_sha256': release, 'source_cdb_sha256': cdb,
            'canonical_matches': actual_matches, 'source_stats_cells': counts.get('cdb_populated_stat_cells'),
            'parity_verified': True, 'full_integrity_receipt_verified': True,
            'primary_cdb_unchanged': True, 'production_switched': False}


def live_release_manifest_sha256() -> str:
    """Two metadata reads catch in-flight movement; no private row download."""
    values = []
    for _ in range(2):
        try:
            proc = subprocess.run(
                ['gh', 'api', f'repos/{RELEASE_REPO}/releases/tags/{RELEASE_TAG}'],
                capture_output=True, text=True, check=False)
        except FileNotFoundError as e:
            raise RuntimeError('Authenticated gh CLI is required for live parity') from e
        if proc.returncode:
            raise RuntimeError('Unable to inspect authenticated current CDB release metadata')
        obj = json.loads(proc.stdout)
        if obj.get('tag_name') != RELEASE_TAG:
            raise ValueError('Unexpected CDB release')
        assets = obj.get('assets', [])
        manifests = [x for x in assets if x.get('name') == 'history_manifest.json']
        partitions = [x for x in assets if re.fullmatch(r'history-\d{4}\.parquet', x.get('name') or '')]
        if len(manifests) != 1 or len(partitions) != 78:
            raise ValueError('Incomplete live CDB release inventory')
        if len({x.get('name') for x in partitions}) != 78 or any(
            not isinstance(x.get('digest'), str) or
            not x['digest'].startswith('sha256:') or
            not valid_sha(x['digest'][7:]) or
            not isinstance(x.get('id'), int)
            for x in partitions
        ):
            raise ValueError('Unverified or duplicate live CDB partition metadata')
        digest = manifests[0].get('digest')
        if not isinstance(digest, str) or not valid_sha(digest.removeprefix('sha256:')) or not digest.startswith('sha256:'):
            raise ValueError('Invalid CDB release manifest digest')
        values.append((digest[7:], manifests[0].get('id'),
                       tuple(sorted((x.get('name'), x.get('digest'), x.get('id')) for x in partitions))))
    if values[0] != values[1]:
        raise ValueError('Live CDB release changed during freshness check')
    return values[0][0]


def inspect(folder: Path, *, verify_live: bool = False):
    folder = folder.resolve()
    active = read_json(folder / 'current-secondary.json')
    result = validate_snapshot(folder, active)
    result['schema'] = 'DIL_SECONDARY_HEALTH_V1'
    result['status'] = 'PINNED_SECONDARY_VERIFIED_FRESHNESS_UNCHECKED'
    result['data_parity_to_current_primary'] = None
    result['serving_cutover_authorized'] = False
    result['model_training_authorized'] = False
    if verify_live:
        current = live_release_manifest_sha256()
        result['live_cdb_release_manifest_sha256'] = current
        if current != result['source_release_manifest_sha256']:
            result['status'] = 'SECONDARY_LAGGING_BEHIND_PRIMARY'
            result['data_parity_to_current_primary'] = False
        else:
            result['status'] = 'SECONDARY_CURRENT_RELEASE_MATCH_VERIFIED'
            result['data_parity_to_current_primary'] = True
    return result


def rollback(folder: Path, expected_active_filename: str):
    """Explicit compare-and-swap of PRIVATE secondary-only pointers, no service config."""
    folder = folder.resolve()
    lockfile = folder / '.dil-secondary-update.lock'
    with lockfile.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_path = folder / 'current-secondary.json'
        previous_path = folder / 'previous-secondary.json'
        old = read_json(old_path)
        previous = read_json(previous_path)
        if old.get('filename') != expected_active_filename:
            raise ValueError('Active secondary changed; compare-and-swap rejected')
        validate_snapshot(folder, old)
        validate_snapshot(folder, previous)
        temp_prev = folder / '.previous-secondary.json.rollback.tmp'
        temp_cur = folder / '.current-secondary.json.rollback.tmp'
        if temp_prev.exists() or temp_cur.exists():
            raise FileExistsError('Unfinished pointer update; refuse rollback')
        try:
            temp_prev.write_text(json.dumps(old, sort_keys=True, indent=2) + '\n')
            temp_cur.write_text(json.dumps(previous, sort_keys=True, indent=2) + '\n')
            os.replace(temp_prev, previous_path)
            os.replace(temp_cur, old_path)
            if read_json(old_path) != previous:
                raise AssertionError('Rollback pointer read-back mismatch')
            return {'status': 'SECONDARY_POINTER_ROLLED_BACK',
                    'active_filename': previous['filename'],
                    'primary_cdb_modified': False, 'production_switched': False}
        finally:
            temp_prev.unlink(missing_ok=True)
            temp_cur.unlink(missing_ok=True)
            fcntl.flock(lock, fcntl.LOCK_UN)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--secondary-dir', required=True)
    ap.add_argument('--verify-live-cdb', action='store_true')
    ap.add_argument('--rollback-to-previous', action='store_true')
    ap.add_argument('--expect-active-filename', help='Required for guarded rollback')
    ns = ap.parse_args(argv)
    try:
        if ns.rollback_to_previous:
            if not ns.expect_active_filename:
                raise ValueError('Rollback requires --expect-active-filename')
            result = rollback(Path(ns.secondary_dir), ns.expect_active_filename)
        else:
            result = inspect(Path(ns.secondary_dir), verify_live=ns.verify_live_cdb)
        print(json.dumps(result, sort_keys=True))
        if result['status'] == 'SECONDARY_LAGGING_BEHIND_PRIMARY':
            return 3
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'SECONDARY_HEALTH_BLOCKED', 'reason': str(exc)},
                         sort_keys=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())