"""Fail-closed WTA 2026 exact-ID rank stage importer (no direct production I/O).
The workflow, not this module, owns the private single-writer lock, CAS,
immutable backup, and independent persisted full-year readback.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import pandas as pd

YEAR = 2026
ORIGINAL_SHA = 'b945528573a8488a5c03eec66b0987791939313cc1099b12d44a9d4a95893bc6'
STAGE_SHA = 'd8353bb92c8fbca596cf8d423ef926bbeb2d6ae51d3e4ddd686d23837d3976f4'
REPORT_SHA = 'd70c7dce0ce8fc413a226ebff68ab2ae4628e2f8799ec26af6e2980a8f8cf086'
EXPECTED_MATCHES = 9844
EXPECTED_VALUES = 19688
FIELDS = ('player1_rank', 'player2_rank')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest()


def missing(x) -> bool:
    return x is None or bool(pd.isna(x))


def bounded_rank(x):
    if isinstance(x, bool) or not isinstance(x, int) or not (1 <= x <= 10000):
        raise ValueError('Invalid historical rank')
    return x


def read_stage(stage_path, report_path):
    if digest(stage_path) != STAGE_SHA or digest(report_path) != REPORT_SHA:
        raise ValueError('Private audited stage/report SHA mismatch')
    r = json.loads(Path(report_path).read_text())
    if (r.get('status') != 'READ_ONLY_WTA2026_ID_RANK_CDB_GAPS'
            or r.get('canonical_year_sha256') != ORIGINAL_SHA
            or r.get('stage_sha256') != STAGE_SHA
            or r.get('counts', {}).get('candidate_matches') != EXPECTED_MATCHES
            or r.get('counts', {}).get('candidate_rank_cells') != EXPECTED_VALUES
            or r.get('write_authorized') is not False
            or r.get('canonical_mutated') is not False
            or r.get('model_promoted') is not False
            or r.get('provider_api_requests') != 0):
        raise ValueError('Audited source cohort/contract mismatch')
    rows = []
    seen = set()
    with gzip.open(stage_path, 'rt', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            mid = str(o.get('canonical_match_id') or '')
            if not mid or mid in seen or o.get('schema') != 1 or o.get('status') != 'CANDIDATE_NOT_WRITER_APPROVED':
                raise ValueError('Malformed/duplicate stage observation')
            seen.add(mid)
            rows.append(o)
    if len(rows) != EXPECTED_MATCHES or sum(len(o.get('add_only_null_fields') or {}) for o in rows) != EXPECTED_VALUES:
        raise ValueError('Unexpected audited stage count')
    return r, rows


def check_manifest(directory, *, expected_sha=None):
    from tbt.data.history_snapshot import load_manifest
    d = Path(directory)
    m = load_manifest(d)
    v = (m.get('years') or {}).get(str(YEAR)) or {}
    path = d / f'history-{YEAR}.parquet'
    sha = digest(path)
    if v.get('sha256') != sha or v.get('asset') != path.name or (expected_sha and sha != expected_sha):
        raise ValueError('Canonical year changed or manifest hash mismatch')
    frame = pd.read_parquet(path)
    if len(frame) != v.get('rows') or frame['match_id'].isna().any() or frame['match_id'].duplicated().any():
        raise ValueError('Canonical year row identity/count invalid')
    required = set(FIELDS) | {'match_id', 'tour', 'scheduled_at', 'player1_id', 'player2_id', 'provider_context_json'}
    if not required.issubset(frame):
        raise ValueError('Canonical schema changed')
    return frame, sha


def attest_rebase(original, current):
    """Every WTA row and order must be identical across ATP-only intervening write."""
    if len(original) != len(current):
        raise ValueError('Row count changed since original WTA stage')
    if not original['match_id'].equals(current['match_id']):
        raise ValueError('Canonical row IDs/order changed since WTA stage')
    old_wta = original.loc[original['tour'].astype(str).str.lower().eq('wta')].reset_index(drop=True)
    new_wta = current.loc[current['tour'].astype(str).str.lower().eq('wta')].reset_index(drop=True)
    if old_wta.empty or len(old_wta) < 30000:
        raise ValueError('WTA annual match regression')
    pd.testing.assert_frame_equal(old_wta, new_wta, check_dtype=False, check_exact=True)
    return len(old_wta)


def apply_exact(current, observations, original_sha=ORIGINAL_SHA):
    if len(observations) != EXPECTED_MATCHES:
        raise ValueError('Unexpected stage rows')
    new = current.copy(deep=True)
    positions = dict(zip(current['match_id'].astype(str), current.index))
    touched = set()
    counts = Counter()
    for o in observations:
        mid = str(o['canonical_match_id'])
        if (o.get('canonical_year') != YEAR or o.get('canonical_year_sha256') != original_sha
                or o.get('temporal_policy') != 'source_before_match_1_to_14_days'):
            raise ValueError('Invalid origin year or stage time scope')
        if mid in touched or mid not in positions:
            raise ValueError('Duplicate/missing canonical match')
        touched.add(mid)
        k = positions[mid]
        old = current.loc[k]
        when = pd.Timestamp(o['scheduled_at'])
        actual_when = pd.Timestamp(old['scheduled_at'])
        if when.tzinfo is None or actual_when.tzinfo is None or when.tz_convert('UTC') != actual_when.tz_convert('UTC'):
            raise ValueError('Canonical match timing differs')
        if (when.year != YEAR or str(old['tour']).lower() != 'wta'
                or str(old['player1_id']) != str(o['player1_id'])
                or str(old['player2_id']) != str(o['player2_id'])):
            raise ValueError('Canonical player identity/scope mismatch')
        sid1, sid2 = (str(o.get('source_player1_id') or ''), str(o.get('source_player2_id') or ''))
        if not sid1 or not sid2 or sid1 == sid2:
            raise ValueError('Unproven source identity')
        weeks = [date.fromisoformat(str(o['source_week_p1'])), date.fromisoformat(str(o['source_week_p2']))]
        if any(not 1 <= (when.date() - week).days <= 14 for week in weeks):
            raise ValueError('Future/same-day/stale source ranking')
        additions = o.get('add_only_null_fields')
        if not isinstance(additions, dict) or not additions or any(key not in FIELDS for key in additions):
            raise ValueError('Invalid field-stage shape')
        for field in FIELDS:
            expected = o.get(f'expected_{field}')
            if expected is not None or not missing(old[field]):
                raise ValueError('Null-only rank precondition failed')
            if field not in additions:
                raise ValueError('Incomplete two-sided WTA source cohort')
            new.at[k, field] = bounded_rank(additions[field])
            counts[f'{field}_filled'] += 1
        raw = old['provider_context_json']
        provider = {} if missing(raw) else json.loads(raw)
        if not isinstance(provider, dict):
            raise ValueError('Non-object canonical provider context')
        witness = {'source': 'sackmann_wta_weekly_verified_id_plus_official_2026',
                   'as_of_player1': weeks[0].isoformat(), 'as_of_player2': weeks[1].isoformat(),
                   'source_player1_id': sid1, 'source_player2_id': sid2,
                   'point_in_time': True, 'audit_run': 38124637314}
        if '_tbt_rank_provenance' in provider and provider['_tbt_rank_provenance'] != witness:
            raise ValueError('Existing rank provenance collision')
        provider['_tbt_rank_provenance'] = witness
        new.at[k, 'provider_context_json'] = json.dumps(provider, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        counts['changed_matches'] += 1
    if counts['changed_matches'] != EXPECTED_MATCHES or sum(counts[f'{x}_filled'] for x in FIELDS) != EXPECTED_VALUES:
        raise ValueError('Unexpected delta')
    cols = [c for c in current if c not in {*FIELDS, 'provider_context_json'}]
    pd.testing.assert_frame_equal(current[cols], new[cols], check_dtype=False, check_exact=True)
    untouched = ~current['match_id'].astype(str).isin(touched)
    pd.testing.assert_frame_equal(current.loc[untouched], new.loc[untouched], check_dtype=False, check_exact=True)
    return new, dict(counts)


def run(mode, source_original_dir, current_dir, after_dir, stage_file, stage_report):
    from tbt.data.history_snapshot import update_year_manifest
    if mode not in ('dry-run', 'write', 'verify'):
        raise ValueError('Unknown mode')
    source_original_dir, current_dir, after_dir = map(Path, (source_original_dir, current_dir, after_dir))
    _, rows = read_stage(stage_file, stage_report)
    original, _ = check_manifest(source_original_dir, expected_sha=ORIGINAL_SHA)
    current, current_sha = check_manifest(current_dir)
    wta_rows = attest_rebase(original, current)
    expected, counts = apply_exact(current, rows)
    if mode == 'write':
        if after_dir.resolve() in (source_original_dir.resolve(), current_dir.resolve()):
            raise ValueError('Refusing in-place canonical writes')
        after_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(current_dir / 'history_manifest.json', after_dir / 'history_manifest.json')
        path = after_dir / f'history-{YEAR}.parquet'
        tmp = path.with_suffix('.parquet.tmp')
        try:
            expected.to_parquet(tmp, engine='pyarrow', compression='zstd', index=False)
            pd.testing.assert_frame_equal(pd.read_parquet(tmp), expected, check_dtype=False, check_exact=True)
            tmp.replace(path)
            update_year_manifest(after_dir, YEAR, {'sha256': digest(path), 'bytes': path.stat().st_size, 'rows': len(expected)}, extra={'coverage_status': 'WTA_2026_verified_ID_point_in_time_weekly_rank_fill'})
        finally:
            tmp.unlink(missing_ok=True)
    elif mode == 'verify':
        actual, _ = check_manifest(after_dir)
        pd.testing.assert_frame_equal(actual, expected, check_dtype=False, check_exact=True)
    return {'schema': 1, 'status': 'full_year_verified' if mode == 'verify' else 'validated_'+mode,
            'mode': mode, 'changed_matches': counts['changed_matches'],
            'new_rank_values': counts['player1_rank_filled'] + counts['player2_rank_filled'],
            'wta_rows_original_vs_current_exact': wta_rows,
            'full_year_rows_checked': len(current), 'previous_rank_overwrites': 0,
            'original_year_sha256': ORIGINAL_SHA, 'current_before_sha256': current_sha,
            'after_year_sha256': digest(after_dir/f'history-{YEAR}.parquet') if mode != 'dry-run' else None,
            'source_stage_sha256': STAGE_SHA, 'source_report_sha256': REPORT_SHA,
            'production_mutated_by_script': False, 'model_trained': False, 'model_promoted': False,
            'provider_api_requests': 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=('dry-run','write','verify'), required=True)
    for key in ('source_original_dir','current_dir','after_dir','stage_file','stage_report','out'):
        ap.add_argument('--'+key.replace('_','-'), required=True, type=Path)
    a = ap.parse_args()
    result = run(a.mode,a.source_original_dir,a.current_dir,a.after_dir,a.stage_file,a.stage_report)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
