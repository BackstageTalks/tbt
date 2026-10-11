"""Independent remote readback of the scheduled collector's exact output."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def verify_added_fields(rows, expected):
    seen = set()
    count = 0
    for row in rows:
        mid = str(row.match_id)
        if mid not in expected:
            continue
        if mid in seen:
            raise ValueError("Duplicate persisted match identity")
        seen.add(mid)
        for key, value in expected[mid].items():
            if (row.stats or {}).get(key) != value:
                raise ValueError("Missing or changed persisted statistic")
            count += 1
    if seen != set(expected):
        raise ValueError("Missing persisted enriched matches")
    return count


def main():
    from _bootstrap import ROOT  # noqa: F401
    from tbt.data.history_snapshot import load_snapshot
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-repository', required=True)
    ap.add_argument('--history-dir', default='.cache/tbt/history')
    args = ap.parse_args()
    root = Path(args.history_dir)
    expected = json.loads((root/'statistics_expected.json').read_text())
    names = [f'history-{int(y):04d}.parquet' for y in expected['years']]
    proof = {}
    with tempfile.TemporaryDirectory() as directory:
        remote = Path(directory)
        for name in names + ['_tbt_bundle_manifest.json']:
            subprocess.run(['gh','release','download','tbt-data-v1','--repo',args.data_repository,
                            '--pattern',name,'--dir',str(remote)], check=True)
        manifest = json.loads((remote/'_tbt_bundle_manifest.json').read_text())['files']
        count = 0
        remaining = dict(expected['added_fields'])
        for name in names:
            digest = hashlib.sha256((remote/name).read_bytes()).hexdigest()
            if digest != hashlib.sha256((root/name).read_bytes()).hexdigest() or digest != manifest[name]['sha256']:
                raise ValueError('Persisted partition differs from collected output or manifest')
            rows = load_snapshot(remote/name)
            ids = {str(row.match_id) for row in rows}
            subset = {mid: remaining[mid] for mid in ids & remaining.keys()}
            count += verify_added_fields(rows, subset)
            for mid in subset:
                del remaining[mid]
            proof[name] = digest
        if remaining:
            raise ValueError('Missing enriched matches in persisted partitions')
    collection = json.loads((root/'download_report.json').read_text())
    if count != collection.get('statistics_data_value', {}).get('new_statistic_values', 0):
        raise ValueError('Collector field count differs from independent readback')
    report = {'status':'VERIFIED' if count else 'VERIFIED_NO_NEW_FIELDS',
              'persisted_new_statistic_values':count, 'partition_sha256':proof,
              'note':'Exact remote/local partition hashes and all proposed new fields verified; no accuracy claim.'}
    (root/'statistics_readback.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
