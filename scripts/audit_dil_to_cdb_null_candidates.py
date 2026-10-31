#!/usr/bin/env python3
"""Read-only, aggregate-only DIL -> CURRENT CDB NULL-stat reverse audit.

No match-level logs, writes, or source promotion. The CDB is authoritative;
a verified value in DIL is not automatically a source-attested import value.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3

SCHEMA = 'DIL_TO_CDB_NULL_CANDIDATES_READONLY_V1'
RATES = frozenset(('first_serve_win','second_serve_win','service_points_won',
                   'return_points_won','first_strike_serve_win','return_in_play_rate',
                   'return_deep_rate','break_point_serve_win','break_point_return_win',
                   'net_points_win','attacking_points_rate','unforced_error_rate'))
COUNTS = frozenset(('aces','double_faults'))
APPROVED = frozenset(f'{side}_{name}' for side in ('p1','p2') for name in RATES|COUNTS)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(8*1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def read_obj(raw):
    result = json.loads(raw or '{}', parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    if not isinstance(result, dict):
        raise ValueError('Stats JSON is not an object')
    return result


def valid_field(key, value) -> bool:
    if key not in APPROVED or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        return False
    part = key[3:]
    if part in RATES:
        return 0 <= value <= 1
    return value >= 0 and int(value) == value


def is_missing(value):
    return value is None or (isinstance(value,str) and value.strip().lower() in ('','none','nan','null','unknown','n/a'))


def same(a,b):
    if type(a) in (int,float) and type(b) in (int,float):
        return abs(a-b) <= 1e-9
    return a == b


def scan(cdb: Path, dil: Path, receipt_path: Path, parity_path: Path, *,
         start_year=2016, end_year=2026, ensure_sha=True):
    cdb, dil = cdb.resolve(), dil.resolve()
    if cdb == dil or not cdb.is_file() or not dil.is_file():
        raise ValueError('Two different existing read-only DBs required')
    receipt = json.loads(receipt_path.read_text())
    parity = json.loads(parity_path.read_text())
    if (receipt.get('schema') != 'BLINQ_FULL_CDB_COMPARE_EXPORT_V2'
        or receipt.get('status') != 'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY'
        or receipt.get('source_partition_count') != 78
        or parity.get('status') != 'VERIFIED_CURRENT_CDB_PARITY'
        or parity.get('full_integrity_check') is not True
        or parity.get('secondary_promotion_allowed') is not True
        or parity.get('source_cdb_sha256') != receipt.get('export_sqlite_sha256')
        or parity.get('source_release_manifest_sha256') != receipt.get('source_release_manifest_sha256')
        or not 1940 <= start_year <= end_year <= 2026):
        raise ValueError('CDB source receipt / independent full parity not attested')
    if ensure_sha and sha256(cdb) != receipt['export_sqlite_sha256']:
        raise ValueError('CDB source snapshot SHA mismatch')
    counts = Counter()
    by_tour_year: dict[str, Counter] = defaultdict(Counter)
    by_metric = Counter()
    with sqlite3.connect(dil.as_uri()+'?mode=ro&immutable=1', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        cdb_uri = cdb.as_uri()+'?mode=ro&immutable=1'
        db.execute('ATTACH DATABASE ? AS current_cdb',(cdb_uri,))
        fields_cdb = {row[1] for row in db.execute('PRAGMA current_cdb.table_info(cdb_matches)')}
        fields_dil = {row[1] for row in db.execute('PRAGMA table_info(canonical_matches)')}
        if not {'match_id','stats_json'}.issubset(fields_cdb) or not {'match_id','tour','source_year','stats_json'}.issubset(fields_dil):
            raise ValueError('Unsupported current CDB / DIL SQL schema')
        has_overlay = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dil_enrichment_compact'").fetchone() is not None
        if has_overlay:
            overlay_cols = {row[1] for row in db.execute('PRAGMA table_info(dil_enrichment_compact)')}
            if not {'match_id','json_metrics'}.issubset(overlay_cols):
                raise ValueError('Malformed DIL overlay schema')
        extra_join = 'LEFT JOIN dil_enrichment_compact e ON e.match_id=d.match_id' if has_overlay else ''
        e_field = 'e.json_metrics' if has_overlay else "'{}'"
        query = f'''SELECT d.tour,d.source_year,d.stats_json,c.stats_json,{e_field},c.match_id
                FROM canonical_matches d JOIN current_cdb.cdb_matches c ON c.match_id=d.match_id
                {extra_join} WHERE d.source_year BETWEEN ? AND ? ORDER BY d.match_id'''
        for tour,year,dil_text,cdb_text,overlay_text,match_id in db.execute(query,(start_year,end_year)):
            counts['matched_existing_canonical_matches'] += 1
            label = f'{str(tour).upper()} {year}'
            by_tour_year[label]['matches'] += 1
            canonical, source, overlay = read_obj(dil_text),read_obj(cdb_text),read_obj(overlay_text)
            if not has_overlay:
                overlay = {}
            # An overlay disagreement with base DIL is not trusted, even if CDB is NULL.
            invalid_keys = {k for k,v in (canonical | overlay).items() if not is_missing(v) and not valid_field(k,v)}
            counts['dil_present_metric_values'] += sum(not is_missing(v) for v in (canonical | overlay).values())
            for key in set(canonical)|set(overlay):
                value = overlay[key] if key in overlay else canonical.get(key)
                if is_missing(value):
                    continue
                if not is_missing(source.get(key)):
                    # Existing CDB value wins; never count as an addition.
                    counts['already_populated_cdb_cells'] += 1
                    continue
                counts['dil_present_cdb_null_cells'] += 1
                by_tour_year[label]['cdb_null_candidates_raw'] += 1
                if key in invalid_keys:
                    counts['invalid_or_unsupported_null_cells'] += 1
                    continue
                if (key in overlay and not is_missing(canonical.get(key))
                        and not same(overlay[key],canonical[key])):
                    counts['intra_dil_overlay_conflicts'] += 1
                    continue
                counts['type_valid_cdb_null_cells_needing_provenance'] += 1
                by_tour_year[label]['type_valid_needing_provenance'] += 1
                by_metric[key] += 1
        if not counts['matched_existing_canonical_matches']:
            raise ValueError('Empty join to canonical CDB; refusing false zero-delta pass')
        # Never write candidate event-level rows or call a canonical writer.
        db.execute('DETACH DATABASE current_cdb')
    if ensure_sha and sha256(cdb) != receipt['export_sqlite_sha256']:
        raise ValueError('CDB changed during readonly reverse audit')
    return {
        'schema':SCHEMA,'status':'READ_ONLY_SOURCE_PROVENANCE_PENDING',
        'cdb_manifest_sha256':receipt['source_release_manifest_sha256'],
        'cdb_sqlite_sha256':receipt['export_sqlite_sha256'],
        'years':[start_year,end_year],
        'counts':dict(counts),
        'type_valid_candidate_fields':dict(sorted(by_metric.items())),
        'by_tour_year':{k:dict(v) for k,v in sorted(by_tour_year.items())},
        'canonical_write_authorized':False,
        'ready_for_existing_cdb_writer':0,
        'production_cdb_changed':False,
        'api_requests':0,
        'note':'Matching match IDs and numeric validity alone do NOT prove independent source provenance or a release-safe import.',
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('cdb','dil','export-receipt','parity-report','out'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--start-year',type=int,default=2016)
    p.add_argument('--end-year',type=int,default=2026)
    args=p.parse_args()
    if args.out.exists():
        p.error('Output exists; refusing overwrite')
    report=scan(args.cdb,args.dil,args.export_receipt,args.parity_report,start_year=args.start_year,end_year=args.end_year)
    args.out.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    # This report contains ONLY aggregate counts, no match/player identities.
    print(json.dumps(report,sort_keys=True))

if __name__=='__main__':
    main()
