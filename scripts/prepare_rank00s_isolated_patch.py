"""ATP 2000-2009 exact NULL-only rank adapter; ISOLATED FILES ONLY.

No network, GitHub API, secrets, writer-lock manipulation, release publishing,
model changes or production paths. This tool does not authorize CDB writes.
Only a separately governed existing publisher can use the resulting review
artifacts after verified rights, identity proofs, restore and live CAS/readback.
Preview files deliberately use preview- names: they are not publishable
canonical year partitions and no canonical manifest is generated.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pandas as pd

SOURCE_ZIP_SHA = '58cdba41d83439c87bcbff435ea0a8e327b92b4d9a444d7add281e7a31d1f2cc'
SOURCE_CSV_SHA = '1d17593dcb12df7df6916892049ca5d0f0e1b4d874df77421e0c65967467094a'
CANONICAL_MANIFEST_SHA = 'ac33267d6d51f5e36c1ad2efc2134fad5155f347044bdb40d24ef94d68b2f984'
PARTITIONS = {
    2000: '224181d0a498b634bc058e0cf9e8d188dfc14c779fe5990cd6365442c618e022',
    2001: '2e8e051eaeffc9faa9e596fc5fdcca534b5f054094fd110cae5ae13ab51eb1d9',
    2002: '4f0c1b6e5663e2b3570ddc77f638a10b73203cac36ddd1971b08f073c96ad8ba',
    2003: '35a71fb0c922f2ddcd435bc469c0f03f2f1e218dfd28bf094888f9b550b7e75a',
    2004: '3b620cb493ea75824bc0c229c473030b0c120729a3d782fe3b6df822fca9842a',
    2005: '382a91568211641f03ae4bd69f713f99266a53d187333db928c45e96788cc9a3',
    2006: '07ab9cb72b85265a47433a3e150bf2c0adf93576793682e1fc21d657f985462e',
    2007: '6c42083466fd503415d05e3054b11903b5f09c880d9a9ec94e8ef73b33772e82',
    2008: '44e241f0e2163bd6c7562d5917479b2b67334907e7d67a3894e4b1e4e51f520f',
    2009: '1fcaacc59262ebc8a09e35988bf52359cd53af3ce76c7a6c13f30de64735fa5d',
}
FIELDS = frozenset(('player1_rank', 'player2_rank'))
COLUMNS = frozenset(('match_id', 'tour', 'scheduled_at', 'player1_id', 'player2_id',
                     'player1_rank', 'player2_rank'))

class GateError(ValueError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def json_object(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'),
                       parse_constant=lambda v: (_ for _ in ()).throw(GateError(v)))
    if not isinstance(value, dict):
        raise GateError('Expected a JSON object')
    return value


def stage_from_preflight(stage_path, report_path):
    """Review-only signed-by-digest pair. Does NOT attest real-world identity."""
    report = json_object(report_path)
    if (report.get('state') != 'PREPARED_READONLY_NO_CDB_WRITE'
            or report.get('history_manifest_sha256') != CANONICAL_MANIFEST_SHA
            or report.get('source_sha256') != SOURCE_ZIP_SHA
            or report.get('canonical_writes') != 0
            or report.get('safe_for_production_write') is not False):
        raise GateError('Source or CDB provenance preflight is missing/stale')
    if digest(stage_path) != report.get('stage_sha256'):
        raise GateError('Stage SHA differs from original preflight report')
    rows = []
    with Path(stage_path).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():
                v = json.loads(line, parse_constant=lambda s: (_ for _ in ()).throw(GateError(s)))
                if not isinstance(v, dict):
                    raise GateError('Malformed candidate JSONL')
                rows.append(v)
                if len(rows) > 2000000:
                    raise GateError('Unbounded candidate count')
    if not rows or len(rows) != report.get('candidate_cells'):
        raise GateError('No verified current NULL candidates, or count drift')
    if not isinstance(report.get('crosswalk_players'), int) or report['crosswalk_players'] < 2:
        raise GateError('No two-sided crosswalk coverage')
    return rows, report


def validate_release_files(directory):
    """Fail closed on ANY manifest drift, even when decade partition SHA stable."""
    d = Path(directory)
    if digest(d / 'history_manifest.json') != CANONICAL_MANIFEST_SHA:
        raise GateError('Canonical manifest release changed: fresh preflight required')
    for year, sha in PARTITIONS.items():
        if digest(d / f'history-{year}.parquet') != sha:
            raise GateError('Canonical partition drift for '+str(year))


def rank_value(value):
    if type(value) is not int or not 1 <= value <= 30000:
        raise GateError('Candidate rank must be bounded integer (no bool/float)')
    return value


def nil(v):
    try:
        r = pd.isna(v)
        return isinstance(r, bool) and r
    except (TypeError, ValueError):
        return v is None


def utc(value):
    try:
        t = pd.Timestamp(value)
        if t.tzinfo is None:
            raise GateError('Missing UTC timestamp timezone')
        return t.tz_convert('UTC')
    except (ValueError, TypeError) as exc:
        raise GateError('Bad candidate match timestamp') from exc


def apply_exact(before, rows):
    """Immutable in-memory exact NULL-only delta; no disk/network mutation."""
    if set(before) != set(PARTITIONS):
        raise GateError('Require all ten original years, not a partial snapshot')
    by_id, result, touched = {}, {}, set()
    for year in PARTITIONS:
        frame = before[year]
        if not COLUMNS.issubset(frame.columns):
            raise GateError('Canonical schema missing required column')
        id_values = frame['match_id'].astype(str)
        if id_values.duplicated().any() or not id_values.all() or (id_values == '').any():
            raise GateError('Canonical match ID duplicate or blank')
        by_id[year] = dict(zip(id_values, frame.index))
        result[year] = frame.copy(deep=True)
    seen, counters = set(), Counter()
    for candidate in rows:
        if not isinstance(candidate, dict):
            raise GateError('Malformed candidate')
        year = candidate.get('canonical_year')
        field = candidate.get('field')
        mid = candidate.get('match_id')
        if (type(year) is not int or year not in PARTITIONS or field not in FIELDS
                or not isinstance(mid, str) or not mid or (year, mid, field) in seen):
            raise GateError('Bad/duplicate candidate key or year')
        seen.add((year, mid, field))
        if (candidate.get('status') != 'REVIEW_ONLY_NO_WRITE'
                or candidate.get('expected_current_value', 'missing') is not None
                or candidate.get('source_csv_sha256') != SOURCE_CSV_SHA
                or candidate.get('source_baseline_history_manifest_sha256') != CANONICAL_MANIFEST_SHA
                or candidate.get('canonical_partition_sha256') != PARTITIONS[year]):
            raise GateError('Candidate provenance, NULL-CAS or status mismatch')
        if mid not in by_id[year]:
            raise GateError('Candidate match absent from pinned CDB year')
        source_id = candidate.get('source_player_id')
        if (not isinstance(source_id, str) or not source_id.isascii() or
                not source_id.isdecimal() or source_id == '104711'):
            raise GateError('Unverified/ambiguous source player ID')
        ix = by_id[year][mid]
        original = before[year].loc[ix]
        if str(original['tour']).lower() != 'atp':
            raise GateError('Candidate is not ATP tour')
        for key in ('player1_id','player2_id'):
            if str(original[key]) != candidate.get('canonical_'+key):
                raise GateError('Candidate/canonical participant mismatch')
        when = utc(original['scheduled_at'])
        if when.year != year:
            raise GateError('Wrong canonical UTC year')
        try:
            source_day = pd.Timestamp(candidate['source_date'])
        except (TypeError, ValueError, KeyError) as exc:
            raise GateError('Missing source ranking date') from exc
        if source_day.tzinfo is not None:
            raise GateError('Expected calendar-date snapshot')
        days = (when.date() - source_day.date()).days
        if not 1 <= days <= 14:
            raise GateError('Ranking snapshot is not strictly pre-match within 14 days')
        rank = rank_value(candidate.get('candidate_value'))
        if not nil(original[field]):
            raise GateError('Non-NULL rank overwrite forbidden; rerun current preflight')
        result[year].at[ix, field] = rank
        touched.add((year, mid))
        counters[field+'_added'] += 1
    if not touched:
        raise GateError('No approved local candidates')
    for year in PARTITIONS:
        beforeframe, afterframe = before[year], result[year]
        cols = [col for col in beforeframe.columns if col not in FIELDS]
        pd.testing.assert_frame_equal(beforeframe[cols], afterframe[cols], check_dtype=True)
        untouched = ~beforeframe['match_id'].astype(str).isin({mid for y, mid in touched if y == year})
        pd.testing.assert_frame_equal(beforeframe.loc[untouched], afterframe.loc[untouched], check_dtype=True)
    counters['matches_changed'] = len(touched)
    counters['rank_cells_added'] = len(rows)
    counters['existing_values_overwritten'] = 0
    return result, dict(counters)


def run(*, baseline_dir, stage_path, report_path, output_dir):
    base, out = Path(baseline_dir), Path(output_dir)
    if base.resolve() == out.resolve() or base.resolve() in out.resolve().parents:
        raise GateError('Output must be outside canonical baseline directory')
    if out.exists() and any(out.iterdir()):
        raise GateError('Output directory must be empty for isolated patch')
    validate_release_files(base)
    rows, report = stage_from_preflight(stage_path, report_path)
    original = {y: pd.read_parquet(base / f'history-{y}.parquet') for y in PARTITIONS}
    patched, counts = apply_exact(original, rows)
    validate_release_files(base)
    if out.exists():
        raise GateError('Output directory must not preexist')
    out.mkdir(parents=True)
    # Create non-release marker before any possibly partial Parquet output.
    (out / 'NOT_FOR_CDB_RELEASE.txt').write_text(
        'ISOLATED rank00s PREVIEW ONLY. NOT A CANONICAL CDB RELEASE.\n', encoding='utf-8')
    assets = {}
    modified_years = sorted({int(x['canonical_year']) for x in rows})
    for year in modified_years:
        dest = out / f'preview-history-{year}.parquet'
        patched[year].to_parquet(dest, engine='pyarrow', compression='zstd', index=False)
        pd.testing.assert_frame_equal(pd.read_parquet(dest), patched[year], check_dtype=True)
        assets[dest.name] = digest(dest)
    result = {'state':'ISOLATED_REVIEW_ONLY_NOT_PRODUCTION','base_manifest_sha256':CANONICAL_MANIFEST_SHA,
              'source_zip_sha256':SOURCE_ZIP_SHA,'original_candidate_stage_sha256':digest(stage_path),
              'after_sha256':assets, 'counts':counts, 'modified_years':modified_years,
              'production_writes':0, 'write_authorized':False,'requires':'separate source rights, actual identity proof, backed-up single-writer live CAS and independent remote readback'}
    (out/'rank00s_isolated_report.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-dir',type=Path,required=True)
    p.add_argument('--stage-path',type=Path,required=True)
    p.add_argument('--report-path',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(run(**vars(args)),sort_keys=True))


if __name__ == '__main__':
    main()
