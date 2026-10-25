#!/usr/bin/env python3
"""Independent, read-only CDB -> DIL secondary parity gate.

Never repairs rows. Only verified current CDB export and isolated DIL paths are
accepted. No per-match information is emitted to logs or the report.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from finalize_dil_from_cdb_v2 import (
    CORE, FIELDS, METADATA, comparable_equal, core_difference, json_obj, miss,
)


def _readonly(path: Path):
    if not path.is_file():
        raise FileNotFoundError('Required secondary parity input missing')
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)


def file_sha256(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def nested_subset(actual, expected):
    """Treat DIL-only extra context as an allowed source-independent enrichment."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and nested_subset(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return comparable_equal(actual, expected) if (
        isinstance(actual, (int, float)) and isinstance(expected, (int, float))
    ) else actual == expected


def metadata_comparison(field, present, canonical):
    if field == 'provider_context_json':
        source = json_obj(canonical)
        if not source:
            return 'not_required'
        current = json_obj(present)
        if not current:
            return 'missing'
        return 'matched' if nested_subset(current, source) else 'conflicting'
    if miss(canonical):
        return 'not_required'
    if miss(present):
        return 'missing'
    if field in ('player1_rank', 'player2_rank', 'best_of', 'indoor'):
        return 'matched' if comparable_equal(present, canonical) else 'conflicting'
    return 'matched' if str(present).strip() == str(canonical).strip() else 'conflicting'


def audit(cdb_path, dil_path, cdb_sha256, *, full_integrity=False, attest=None):
    cdb_path, dil_path = Path(cdb_path).resolve(), Path(dil_path).resolve()
    if len(cdb_sha256) != 64 or file_sha256(cdb_path) != cdb_sha256:
        raise ValueError('CDB immutable SQLite checksum mismatch')
    if cdb_path == dil_path:
        raise ValueError('DIL and CDB paths must be different')
    if attest is None:
        raise ValueError('Immutable 78-part CDB export receipt required')
    receipt = json.loads(Path(attest).read_text(encoding='utf-8'))
    if (receipt.get('schema') != 'BLINQ_FULL_CDB_COMPARE_EXPORT_V2'
            or receipt.get('status') != 'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY'
            or receipt.get('source_partition_count') != 78
            or receipt.get('export_sqlite_sha256') != cdb_sha256
            or receipt.get('source_matches', 0) < 1):
        raise ValueError('Unverified CDB export receipt')
    counts = Counter()
    with closing(_readonly(cdb_path)) as cdb, closing(_readonly(dil_path)) as dil:
        schemas = [
            (cdb, 'cdb_matches', set(FIELDS)),
            (dil, 'canonical_matches', set(FIELDS)),
        ]
        for connection, table, required in schemas:
            fields = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            if not required.issubset(fields):
                raise ValueError(f'Schema incompatible with secondary audit: {table}')
        # The source exporter and DIL both define unique match IDs.
        ids = dil.execute('SELECT match_id FROM canonical_matches ORDER BY match_id')
        cdb_ids = cdb.execute('SELECT match_id FROM cdb_matches ORDER BY match_id')
        a, b = next(ids, None), next(cdb_ids, None)
        while a is not None or b is not None:
            if a is None or (b is not None and b[0] < a[0]):
                counts['missing_cdb_match_ids_in_dil'] += 1
                b = next(cdb_ids, None)
            elif b is None or a[0] < b[0]:
                counts['dil_canonical_ids_not_in_cdb'] += 1
                a = next(ids, None)
            else:
                counts['shared_ids'] += 1
                a = next(ids, None)
                b = next(cdb_ids, None)
        has_overlay = dil.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dil_enrichment_compact'").fetchone() is not None
        field_list=','.join('"'+field+'"' for field in FIELDS)
        matches = dil.execute('SELECT '+field_list+' FROM canonical_matches ORDER BY match_id')
        # Indexed point queries into immutable CDB; bounded-memory across full corpus.
        query_cdb = cdb.cursor()
        query_overlay = dil.cursor()
        for row in matches:
            m = dict(zip(FIELDS, row))
            matched = query_cdb.execute('SELECT '+field_list+' FROM cdb_matches WHERE match_id=?',
                        (m['match_id'],)).fetchone()
            if matched is None:
                continue
            source = dict(zip(FIELDS, matched))
            if core_difference(m, source):
                counts['core_mismatched_matches'] += 1
            for field in METADATA:
                relation = metadata_comparison(field, m[field], source[field])
                if relation != 'not_required':
                    counts['cdb_populated_metadata_fields'] += 1
                    counts['cdb_metadata_'+relation+'_fields'] += 1
            stats_dil = json_obj(m['stats_json'])
            stats_cdb = json_obj(source['stats_json'])
            overlay = {}
            if has_overlay:
                entry = query_overlay.execute('SELECT json_metrics FROM dil_enrichment_compact WHERE match_id=?', (m['match_id'],)).fetchone()
                if entry: overlay = json_obj(entry[0])
            for k, value in stats_cdb.items():
                if miss(value):
                    continue
                counts['cdb_populated_stat_cells'] += 1
                actual = overlay[k] if k in overlay else stats_dil.get(k)
                if miss(actual):
                    counts['cdb_stat_cells_missing_effective_dil'] += 1
                elif not comparable_equal(value, actual):
                    counts['cdb_stat_cells_conflicting_effective_dil'] += 1
                else:
                    counts['cdb_stat_cells_matched'] += 1
        expected_count = receipt['source_matches']
        real_count = cdb.execute('SELECT count(*) FROM cdb_matches').fetchone()[0]
        counts['cdb_matches'] = real_count
        counts['dil_matches'] = dil.execute('SELECT count(*) FROM canonical_matches').fetchone()[0]
        if real_count != expected_count:
            raise ValueError('Export receipt/source row count changed')
        for connection, prefix in ((cdb, 'cdb'), (dil, 'dil')):
            result = connection.execute('PRAGMA integrity_check' if full_integrity else 'PRAGMA quick_check').fetchone()
            if result != ('ok',):
                counts[prefix + '_sqlite_check_failures'] += 1
            if full_integrity:
                counts[prefix + '_foreign_key_failures'] = sum(1 for _ in connection.execute('PRAGMA foreign_key_check'))
    if file_sha256(cdb_path) != cdb_sha256:
        raise ValueError('CDB export changed while parity was checked')
    failures = ('missing_cdb_match_ids_in_dil', 'dil_canonical_ids_not_in_cdb',
                'core_mismatched_matches', 'cdb_metadata_missing_fields',
                'cdb_metadata_conflicting_fields', 'cdb_stat_cells_missing_effective_dil',
                'cdb_stat_cells_conflicting_effective_dil', 'cdb_sqlite_check_failures',
                'dil_sqlite_check_failures', 'cdb_foreign_key_failures', 'dil_foreign_key_failures')
    passed = full_integrity and all(counts.get(x, 0) == 0 for x in failures)
    return {'schema': 'DIL_SECONDARY_STRICT_CURRENT_CDB_PARITY_V1',
            'status': ('VERIFIED_CURRENT_CDB_PARITY' if passed else
                       'PRELIMINARY_CHECK_ONLY' if not full_integrity and
                       all(counts.get(x, 0) == 0 for x in failures) else
                       'BLOCKED_CURRENT_CDB_PARITY'),
            'source_cdb_sha256': cdb_sha256,
            'source_release_manifest_sha256': receipt['source_release_manifest_sha256'],
            'full_integrity_check': full_integrity,
            'counts': dict(counts), 'secondary_promotion_allowed': passed,
            'production_cdb_modified': False,
            'production_cdb_replaced': False,
            'model_training_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cdb', required=True)
    parser.add_argument('--dil', required=True)
    parser.add_argument('--cdb-sha256', required=True)
    parser.add_argument('--export-receipt', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--full-integrity', action='store_true')
    args = parser.parse_args()
    result = audit(args.cdb, args.dil, args.cdb_sha256,
                   full_integrity=args.full_integrity, attest=args.export_receipt)
    target = Path(args.out)
    if target.exists():
        raise FileExistsError('Refusing to overwrite prior parity evidence')
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'counts': result['counts']}))
    return 0 if result['secondary_promotion_allowed'] else 2


if __name__ == '__main__':
    sys.exit(main())