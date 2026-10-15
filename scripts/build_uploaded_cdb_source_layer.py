#!/usr/bin/env python3
"""Deterministic private CDB source layer for operator ATP/WTA 2025-26 CSVs.

This is a source-only ledger, not a canonical ID resolver or model feature feed.
Does not import, write, or touch a canonical CDB partition.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile

RAW_SHA = '8202ff4b485495546e507317357b9f1c3c84ad9b5f806931044bfede16a9783d'
STAGE_SHA = 'e66e6de58d70801fe2dca7b049f75f442237516a7e5042947b892d63daa1dae8'
RAW_ROWS, ODDS_ROWS, STAGE_ROWS, STAGE_VALUES = 10927, 5791, 9741, 154342


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def gzip_bytes(data: bytes) -> bytes:
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0, compresslevel=6) as stream:
        stream.write(data)
    return out.getvalue()


def ledger_bytes(items: list[dict]) -> bytes:
    return gzip_bytes((''.join(canonical(x) + '\n' for x in items)).encode('utf-8'))


def verified_source(raw_path: Path) -> tuple[dict, dict]:
    raw = raw_path.read_bytes()
    if digest(raw) != RAW_SHA:
        raise ValueError('Untrusted raw archive SHA256')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:
            raise ValueError('Invalid source ZIP CRC')
        qa = json.loads(z.read('audit/qa_report.json'))
        if (qa.get('four_match_files_rows'), qa.get('closing_odds_rows'), qa.get('qa_findings_count')) != (RAW_ROWS, ODDS_ROWS, 70):
            raise ValueError('Unexpected source QA report')
        raw_members = {}
        for name, info in qa['files'].items():
            content = z.read('raw/' + name)
            if digest(content) != info['sha256'] or len(content) != info['bytes']:
                raise ValueError('Per-CSV original bytes mismatch: ' + name)
            raw_members[name] = content
        quarantine_lines = z.read('audit/quarantine.jsonl').decode('utf-8').splitlines()
        quarantine = [json.loads(x) for x in quarantine_lines if x.strip()]
        if len(quarantine) != 70:
            raise ValueError('QA quarantine row count mismatch')
    return {'archive': raw, 'qa': qa, 'quarantine': quarantine}, raw_members


def build(raw_path: Path, stage_path: Path, output: Path) -> dict:
    source, members = verified_source(raw_path)
    stage_blob = stage_path.read_bytes()
    if digest(stage_blob) != STAGE_SHA:
        raise ValueError('Untrusted normalized stage SHA256')
    with gzip.open(io.BytesIO(stage_blob), 'rt', encoding='utf-8') as g:
        stage = [json.loads(x) for x in g if x.strip()]
    if len(stage) != STAGE_ROWS or sum(len(x['winner_stats']) + len(x['loser_stats']) for x in stage) != STAGE_VALUES:
        raise ValueError('Untrusted normalized stage counts')
    stage_keys = {(x['source_tour'], str(x['source_match_id'])) for x in stage}
    if len(stage_keys) != STAGE_ROWS:
        raise ValueError('Duplicate validated stage source key')

    issues = defaultdict(list)
    for q in source['quarantine']:
        issues[(q['file'], q['match_id'])].append(q['issue'] + (':' + q['side'] if q.get('side') else ''))
    matches, odds, native = [], [], {}
    for name, data in sorted(members.items()):
        if name.startswith('atp_wta_'):
            continue
        tour = name.split('_', 1)[0].upper()
        season = int(name.split('_')[2].split('(')[0])
        reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
        for line, raw in enumerate(reader, 2):
            event_id = str(raw.get('match_id') or '').strip()
            key = (tour, event_id)
            if not event_id or key in native or raw.get('winner_id') == raw.get('loser_id'):
                raise ValueError('Duplicate/missing source match/player identity')
            native[key] = (name, line, raw)
            flags = sorted(set(issues.get((name, event_id), [])))
            in_stage = key in stage_keys
            matches.append({
                'schema': 1, 'layer': 'SOURCE_VALIDATED',
                'source_scope': 'uploaded_atp_wta_2025_2026', 'source_event_key': f'{tour}:{event_id}',
                'tour': tour, 'season': season, 'source_file': name, 'source_line': line,
                'source_file_sha256': source['qa']['files'][name]['sha256'],
                'source_row_sha256': digest(canonical(raw).encode()),
                'source_event_id': event_id,
                'source_winner_player_id': raw['winner_id'], 'source_loser_player_id': raw['loser_id'],
                'event_start_utc': raw['start_time_utc'], 'score': raw['score'],
                'validated_stat_stage_available': in_stage, 'qa_flags': flags,
                'validation_status': 'QA_REVIEW' if flags else ('VALIDATED_SOURCE_ONLY' if in_stage else 'RAW_SOURCE_ONLY'),
                'raw_columns': raw,
                'source_rights_status': 'UNVERIFIED_PRIVATE_RETENTION_ONLY',
                'canonical_match_id': None, 'canonical_player1_id': None, 'canonical_player2_id': None,
                'import_ready': False, 'write_authorized': False,
                'training_allowed': False, 'prematch_feature_allowed': False,
            })
    if len(native) != RAW_ROWS:
        raise ValueError('Total unique source events unexpectedly changed')
    odds_files = [n for n in members if n.startswith('atp_wta_')]
    if len(odds_files) != 1:
        raise ValueError('Unexpected odds file inventory')
    name = odds_files[0]
    for line, raw in enumerate(csv.DictReader(io.StringIO(members[name].decode('utf-8-sig'))), 2):
        key = (raw['tour'].upper(), raw['match_id'])
        if key not in native:
            raise ValueError('Odds not connected to a native source event')
        _, _, m = native[key]
        if raw['start_time_utc'] != m['start_time_utc']:
            raise ValueError('Odds/native event UTC conflict')
        flags = sorted(set(issues.get((name, raw['match_id']), [])))
        odds.append({
            'schema': 1, 'layer': 'SOURCE_MARKET_OBSERVATION',
            'source_event_key': ':'.join(key), 'source_file': name, 'source_line': line,
            'source_file_sha256': source['qa']['files'][name]['sha256'],
            'source_row_sha256': digest(canonical(raw).encode()),
            'raw_columns': raw, 'qa_flags': flags,
            'source_event_linked': True, 'canonical_match_id': None,
            'quote_capture_utc': None, 'quote_capture_time_proven': False,
            'claimed_closing_odds_unverified': True,
            'training_allowed': False, 'prematch_feature_allowed': False,
            'write_authorized': False,
            'source_rights_status': 'UNVERIFIED_PRIVATE_RETENTION_ONLY',
        })
    if len(odds) != ODDS_ROWS:
        raise ValueError('Odds count mismatch')
    if sum(bool(m['validated_stat_stage_available']) for m in matches) != STAGE_ROWS:
        raise ValueError('Prepared stage identity is not subset of raw unique source keys')
    flagged_matches = sum(bool(m['qa_flags']) for m in matches)
    flagged_odds = sum(bool(o['qa_flags']) for o in odds)
    counts = Counter(x['issue'] for x in source['quarantine'])
    if counts != {'service_counts_inconsistent': 24, 'closing_prob_source_conflict_gt_0_001': 46}:
        raise ValueError('QA type counts mismatch')

    output.mkdir(parents=True, exist_ok=True)
    products = {
        'source-original-raw-20261015.zip': source['archive'],
        'source-matches.jsonl.gz': ledger_bytes(matches),
        'source-market-observations.jsonl.gz': ledger_bytes(odds),
        'source-statistics-validated-stage.jsonl.gz': stage_blob,
        'source-quarantine.jsonl.gz': ledger_bytes(source['quarantine']),
        'source-canonical-links.jsonl.gz': gzip_bytes(b''),
    }
    report = {
        'schema': 'BLINQ_CDB_SOURCE_LAYER_V1', 'status': 'PRIVATE_RETAINED_VALIDATED_UNLINKED',
        'source_sha256': RAW_SHA, 'validated_stage_sha256': STAGE_SHA,
        'source_native_events': len(matches), 'source_market_observations': len(odds),
        'source_market_rows_linked_to_native_event': len(odds),
        'validated_stat_rows': STAGE_ROWS, 'validated_stat_values': STAGE_VALUES,
        'source_event_rows_with_qa_flags': flagged_matches,
        'market_rows_with_qa_flags': flagged_odds, 'quarantine_findings': len(source['quarantine']),
        'quarantine_reasons': dict(sorted(counts.items())),
        'canonical_links': 0, 'canonical_rows_written': 0, 'canonical_cells_written': 0,
        'rights_reuse_approved': False, 'training_allowed': False,
        'prematch_feature_allowed': False, 'new_raw_source_calls': 0,
        'canonical_partition_mutated': False,
        'source_deduplication': 'SHA256 raw files and tour-namespaced source_event_key; earlier uploads byte-identical',
        'canonical_identity_policy': 'NEVER infer canonical event or participant IDs from source namespace',
        'provenance_source': 'user-provided CSVs, upstream attribution/reuse permission unverified',
        'assets': {k: {'sha256': digest(v), 'bytes': len(v)} for k, v in sorted(products.items())},
    }
    products['source-layer-manifest.json'] = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    products['SHA256SUMS'] = (''.join(f'{digest(blob)}  {name}\n' for name, blob in sorted(products.items()))).encode()
    for name, blob in products.items():
        (output / name).write_bytes(blob)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--raw-zip', required=True, type=Path)
    p.add_argument('--validated-stage', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(build(a.raw_zip, a.validated_stage, a.out), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()