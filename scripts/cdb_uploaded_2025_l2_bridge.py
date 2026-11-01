#!/usr/bin/env python3
"""Read-only adapter: vetted opaque ATP 2025 source -> existing private L2 gate.

Output implements tbt-data/scripts/research/reconcile_uploaded_serve_return.py
SOURCE format. This adapter does not produce evidence, attestations or imports.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path

from cdb_uploaded_2025_source_stage import counts_quality, rates, game_score_quality, exact_time

SOURCE_NAME = 'serve_return_source_only.csv.gz'
NAMESPACE = 'uploaded-atp-2025-opaque'
STAGE_SCHEMA = 'BLINQ_UPLOADED_ATP2025_SOURCE_ONLY_V1'
COUNT_KEYS = {'aces':'ace', 'double_faults':'df'}
RATE_KEYS = {
    'first_serve_win':'first_serve_points_won_pct',
    'second_serve_win':'second_serve_points_won_pct',
    'service_points_won':'service_points_won_pct',
    'return_points_won':'return_points_won_pct',
    'break_point_serve_win':'break_points_saved_pct',
    'break_point_return_win':'return_break_points_converted_pct',
}
SHA = re.compile(r'^[a-f0-9]{64}$')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as reader:
        for block in iter(lambda: reader.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def number(value, *, count: bool) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Nonfinite or nonnumeric staged statistic')
    if count:
        if value < 0 or not float(value).is_integer():
            raise ValueError('Invalid integer count')
        return str(int(value))
    if not 0 <= value <= 1:
        raise ValueError('Out-of-range rate')
    return format(value, '.17g')


def convert(source_report: Path, stage: Path, original: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError('Do not replace any preexisting bridge bundle')
    meta = json.loads(source_report.read_text(encoding='utf-8'))
    source_sha = meta.get('source_sha256', '')
    if (meta.get('schema') != STAGE_SCHEMA
            or meta.get('cdb_write_authorized') is not False
            or meta.get('production_mutated') is not False
            or not SHA.fullmatch(source_sha)
            or not SHA.fullmatch(str(meta.get('source_only_file_sha256','')))
            or digest(original) != source_sha
            or digest(stage) != meta['source_only_file_sha256']):
        raise ValueError('Source-stage manifest or original SHA mismatch; fail closed')
    if meta['counts'].get('source_only_complete_rows', 0) <= 0:
        raise ValueError('No qualified source-only rows')
    header = [
        'side','source_family','source_archive_sha256','source_member','original_line',
        'source_tour','tourney_id','tourney_name','tourney_week','match_num','round',
        'surface','score','winner_id','winner_name','loser_id','loser_name',
        'source_player_id','source_player_name','opponent_source_id','opponent_name',
        'complete_match_score','source_match_id','source_native_namespace',
        'source_claimed_event_time_utc',
        *COUNT_KEYS.values(), *RATE_KEYS.values(),
    ]
    contents = io.StringIO(newline='')
    writer = csv.DictWriter(contents, fieldnames=header, extrasaction='raise')
    writer.writeheader()
    n = 0
    cells = 0
    original_handle = original.open('r', encoding='utf-8-sig', newline='')
    original_reader = csv.DictReader(original_handle)
    current_line = 1
    actual_raw = None
    ids = set()
    event_tuples = set()
    with stage.open('r', encoding='utf-8') as stream:
        for expected_line, raw in enumerate(stream, 1):
            if not raw.strip():
                raise ValueError('Blank stage record')
            row = json.loads(raw)
            if (row.get('import_ready') is not False
                    or row.get('independent_canonical_identity_attested') is not False
                    or row.get('source_id_namespace') != NAMESPACE
                    or row.get('tour') != 'atp'
                    or not isinstance(row.get('line'), int)
                    or row.get('line') < 2
                    or row.get('source_record_id') != f"{NAMESPACE}:{source_sha}:{row['line']}"):
                raise ValueError('Untrusted or allegedly import-ready source observation')
            if row['line'] <= current_line:
                raise ValueError('Stage rows are not in strict original-file order')
            while current_line < row['line']:
                try:
                    actual_raw = next(original_reader)
                except StopIteration as exc:
                    raise ValueError('Staged row beyond original CSV end') from exc
                current_line += 1
            if (actual_raw is None or any(str(actual_raw.get(src_field) or '') != str(row.get(dst_field) or '')
                    for src_field, dst_field in (
                        ('match_id','source_match_id'),('tourney_id','source_tourney_id'),
                        ('winner_id','source_winner_id'),('loser_id','source_loser_id'),
                        ('winner_name','winner_name'),('loser_name','loser_name'),
                        ('tourney_name','tournament'),('surface','surface'),
                        ('round','round'),('score','score'),
                        ('tourney_date','tournament_start')
                    )) or row.get('source_match_num') != int(actual_raw.get('match_num') or -1)
                    or game_score_quality(actual_raw.get('score'),actual_raw.get('best_of')) != 'valid'
                    or exact_time(actual_raw) is None
                    or row.get('source_event_time_utc') != exact_time(actual_raw).isoformat()):
                raise ValueError('Staged event metadata differs from original source')
            count_state, raw_counts = counts_quality(actual_raw)
            if count_state != 'valid' or rates(raw_counts) != {
                    'w':row.get('observations_winner'), 'l':row.get('observations_loser')}:
                raise ValueError('Staged statistical values differ from original source')
            source_mid = str(row.get('source_match_id') or '')
            source_tid = str(row.get('source_tourney_id') or '')
            source_num = row.get('source_match_num')
            w, l = str(row.get('source_winner_id') or ''), str(row.get('source_loser_id') or '')
            names = [str(row.get('winner_name') or ''), str(row.get('loser_name') or '')]
            if (not all((source_mid,source_tid,w,l,*names)) or w==l
                    or source_mid in ids or (source_tid,source_num) in event_tuples
                    or not isinstance(source_num,int)):
                raise ValueError('Duplicate/invalid source-native event or participants')
            ids.add(source_mid)
            event_tuples.add((source_tid,source_num))
            src_stats = (row.get('observations_winner'),row.get('observations_loser'))
            if not all(isinstance(x,dict) for x in src_stats):
                raise ValueError('Missing derived player observations')
            for side, own, opposite, stats in (
                    ('winner', w, l, src_stats[0]), ('loser',l,w,src_stats[1])):
                item = {
                    'side':side, 'source_family':NAMESPACE,
                    'source_archive_sha256':source_sha,
                    'source_member': original.name, 'original_line':str(row['line']),
                    'source_tour':'atp', 'tourney_id':source_tid,
                    'tourney_name':row['tournament'], 'tourney_week':row['tournament_start'],
                    'match_num':str(source_num), 'round':row['round'],
                    'surface':row['surface'], 'score':row['score'],
                    'winner_id':w,'winner_name':names[0],
                    'loser_id':l,'loser_name':names[1],
                    'source_player_id':own, 'source_player_name':names[0] if side=='winner' else names[1],
                    'opponent_source_id':opposite,
                    'opponent_name':names[1] if side=='winner' else names[0],
                    'complete_match_score':'True',
                    'source_match_id':source_mid,'source_native_namespace':NAMESPACE,
                    'source_claimed_event_time_utc':row['source_event_time_utc'],
                }
                if set(stats) - set(COUNT_KEYS) - set(RATE_KEYS):
                    raise ValueError('Unexpected stat key; do not silently drop')
                for source_key,dest_key in COUNT_KEYS.items():
                    if source_key in stats:
                        item[dest_key] = number(stats[source_key],count=True)
                        cells += 1
                for source_key,dest_key in RATE_KEYS.items():
                    if source_key in stats:
                        item[dest_key] = number(stats[source_key],count=False)
                        cells += 1
                writer.writerow(item)
            n += 1
    original_handle.close()
    if n != meta['counts']['source_only_complete_rows'] or cells != meta['counts']['potential_stat_observations']:
        raise ValueError('Stage count/field inventory differs from source report')
    compressed = gzip.compress(contents.getvalue().encode('utf-8'),compresslevel=9,mtime=0)
    member_sha = hashlib.sha256(compressed).hexdigest()
    manifest = {
        'schema':'BLINQ_UPLOADED_ATP2025_EXISTING_L2_GATE_BRIDGE_V1',
        'state':'SOURCE_ONLY_NO_INDEPENDENT_CDB_IDENTITY',
        'files':{SOURCE_NAME:{'sha256':member_sha,'rows':2*n}},
        'source_csv_sha256':source_sha,
        'stage_sha256':digest(stage),
        'source_records':n, 'side_records':n*2,
        'observed_stat_cells':cells, 'source_namespace':NAMESPACE,
        'independent_id_witnesses':0,
        'import_ready':False, 'cdb_write_authorized':False,
        'cdb_writes':0,'provider_requests':0,
        'gate':'tbt-data/scripts/research/reconcile_uploaded_serve_return.py',
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,mode='x',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        z.writestr(SOURCE_NAME,compressed)
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None or hashlib.sha256(z.read(SOURCE_NAME)).hexdigest() != member_sha:
            raise ValueError('Bridge ZIP failed CRC or SHA readback')
    return {**manifest,'bundle_sha256':digest(out)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-report',required=True,type=Path)
    p.add_argument('--stage',required=True,type=Path)
    p.add_argument('--original',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(convert(a.source_report,a.stage,a.original,a.out),sort_keys=True))


if __name__=='__main__':main()