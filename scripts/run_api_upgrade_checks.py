"""Run explicit local regression suites and save evidence; no deployment step."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SUITES = (
    'test_api_upgrade_preflight.py', 'test_verify_cdb_enrichment.py',
    'test_cdb_global_writer_lock.py', 'test_shared_api_budget.py',
    'test_statistics.py', 'test_probe_tennisapi_extended_contract.py',
    'test_market_selection.py', 'test_tennisapi_extra.py',
    'test_tennisapi_extras_jobs.py', 'test_offline_exact_cdb_write.py',
    'test_offline_linked_serve_return_importer.py',
    'test_immutable_training_backup.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New report directory')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(str(root / p) for p in ('', 'api', 'scripts'))
    cmd = [sys.executable, '-m', 'pytest', *(f'tests/{s}' for s in SUITES),
           '-q', '--tb=short', f'--basetemp={out / "temp"}', f'--junitxml={out / "junit.xml"}']
    run = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True,
                         encoding='utf-8', errors='replace', timeout=300)
    (out / 'tests.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    version = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                             capture_output=True, text=True, check=True).stdout.strip()
    files = sorted(set(root.glob('api/**/*.py')) | set(root.glob('scripts/**/*.py')) |
                   {root / 'tests' / name for name in SUITES})
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report = {'state': 'PREPARED', 'base_commit': version,
        'local_regressions': 'PASS' if run.returncode == 0 else 'FAIL',
        'pytest_exit_code': run.returncode, 'suites': SUITES, 'source_sha256': hashes,
        'production_write_authorized': False,
        'live_api_verified': False, 'production_cdb_readback_verified': False,
        'ssd_drive_restore_verified': False,
        'note': 'Local/synthetic regression evidence only. No production approval or live-data certificate.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(run.stdout + run.stderr)
    print(f'Report: {out / "report.json"}')
    return run.returncode


if __name__ == '__main__':
    raise SystemExit(main())
