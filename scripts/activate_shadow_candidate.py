"""Activate a verified frozen model in the candidate slot, never production.

Caller owns the global writer lock. Both mutable bundles are restored on any
failed write/readback; immutable source releases and old shadow rows survive.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from _bootstrap import ROOT
from release_store import ReleaseStore
from tbt.models.artifact import load_model
from tbt.services.shadow_evaluation import build_shadow_report
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256,
    validate_frozen_evidence, exclude_repeated_events,
)

REPO = 'BackstageTalks/tbt-data'
CANDIDATE = 'tbt-model-candidate-v1'
PRODUCTION = 'tbt-model-production-v1'
SHADOW = 'tbt-model-shadow-v1'
MODEL_FILES = ('model.joblib', 'training_report.json', 'promotion_history.json')
SHADOW_FILES = ('shadow_ledger.json', 'shadow_report.json')


def download(tag, directory, names):
    store = ReleaseStore(REPO, tag, directory)
    store.download(extra_names=names, required_names=names, require_bundle_manifest=True)
    return store, {name: (store.directory / name).read_bytes() for name in names}


def publish(store, files):
    for name, raw in files.items():
        (store.directory / name).write_bytes(raw)
    store.upload_bundle([store.directory / name for name in files])


def checked_publish(store, tag, files, readback):
    publish(store, files)
    _, remote = download(tag, readback, tuple(files))
    if remote != files:
        raise RuntimeError(f'Remote readback mismatch: {tag}')


def combine_rows(old, incoming):
    """Preserve historical cohorts; never overwrite an existing prediction."""
    def key(row):
        return tuple(row.get(k) for k in ('match_id', 'production_model_version', 'challenger_model_version'))
    result = [dict(r) for r in old]
    indexed = {key(r): r for r in result}
    if len(indexed) != len(result):
        raise ValueError('Duplicate model-pair match in existing shadow')
    for row in incoming:
        existing = indexed.get(key(row))
        if existing is not None:
            # A subsequent active capture may have legitimately settled a row.
            for field in ('captured_at', 'scheduled_at', 'event_id', 'player1_id', 'player2_id',
                          'production_player1_probability', 'challenger_player1_probability'):
                if existing.get(field) != row.get(field):
                    raise ValueError(f'Conflicting immutable shadow field: {field}')
            continue
        result.append(dict(row))
        indexed[key(row)] = row
    return result


def activate(source_tag, expected_sha, *, cache=None, prospective_only=False, expected_source_sha=None):
    if not re.fullmatch(r'blinq-candidate-frozen-\d+-\d+', source_tag):
        raise ValueError('Only immutable protected candidate releases are accepted')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha):
        raise ValueError('Expected current candidate SHA-256 is required')
    base = Path(cache or ROOT / '.cache/tbt/candidate-activation')
    base.mkdir(parents=True, exist_ok=True)
    from cdb_global_writer_lock import verify
    verify(REPO, ROOT / '.cdb-global-writer-lock.json')
    # Probe every release before ReleaseStore can create anything.
    from release_store import _run_gh
    for tag in (source_tag, CANDIDATE, PRODUCTION, SHADOW):
        probe = _run_gh(['api', f'repos/{REPO}/releases/tags/{tag}'])
        if probe.returncode:
            raise RuntimeError(f'Existing private release inaccessible: {tag}')
    source, fresh = download(source_tag, base / 'source', MODEL_FILES)
    candidate, old = download(CANDIDATE, base / 'candidate', MODEL_FILES)
    _, champion = download(PRODUCTION, base / 'production', MODEL_FILES)
    shadow, old_shadow = download(SHADOW, base / 'shadow', SHADOW_FILES)
    digest = hashlib.sha256(fresh['model.joblib']).hexdigest()
    if prospective_only and (not re.fullmatch(r'[0-9a-f]{64}', expected_source_sha or '')
                             or digest != expected_source_sha):
        raise ValueError('Prospective research requires the exact source model SHA-256')
    current_digest = hashlib.sha256(old['model.joblib']).hexdigest()
    if current_digest not in {expected_sha, digest}:
        raise ValueError('Candidate changed since request; refusing to replace another run')
    model = load_model(str(source.directory / 'model.joblib'))
    prod = load_model(str(base / 'production/model.joblib'))
    report = json.loads(fresh['training_report.json'])
    decision = report.get('promotion_decision') or {}
    if (not model.fitted or not model.version.startswith(('v7.2.1-', 'v7.2.2-'))
            or decision.get('candidate_version') != model.version
            or decision.get('production_version') != prod.version
            or decision.get('promotion_requested') is not False):
        raise ValueError('Fitted artifact / evaluated champion provenance mismatch')
    if prospective_only:
        backup = report.get('immutable_training_backup') or {}
        expected_backup = source_tag.replace('blinq-candidate-frozen-', 'blinq-full-training-backup-')
        if (backup.get('candidate_tag') != source_tag or backup.get('tag') != expected_backup
                or backup.get('champion_sha256') != hashlib.sha256(champion['model.joblib']).hexdigest()
                or not isinstance(backup.get('asset_count'), int) or backup['asset_count'] < 1):
            raise ValueError('Prospective candidate protected backup provenance mismatch')
        if _run_gh(['api', f'repos/{REPO}/releases/tags/{expected_backup}']).returncode:
            raise ValueError('Protected training backup is unavailable')
    else:
        if not (report.get('evaluation_governance') or {}).get('holdout_fingerprint'):
            raise ValueError('Untouched holdout fingerprint missing')
        for label in ('holdout', 'production_holdout'):
            if (report.get(label) or {}).get('n', 0) < 200:
                raise ValueError('Untouched holdout comparison missing')
    incoming = []
    if source_tag == FROZEN_721_TAG and not prospective_only:
        if digest != FROZEN_721_MODEL_SHA256 or model.version != FROZEN_721_VERSION:
            raise ValueError('Pinned original 7.2.1 artifact mismatch')
        _, evidence = download('blinq-frozen-721-private-shadow-v1', base / 'frozen-shadow',
                               ('frozen_721_paired_shadow.json',))
        incoming, _ = validate_frozen_evidence(json.loads(evidence['frozen_721_paired_shadow.json']),
                                              production_version=prod.version)
        incoming = exclude_repeated_events(incoming)
    rows = combine_rows(json.loads(old_shadow['shadow_ledger.json']), incoming)
    status = build_shadow_report(rows, production_model_version=prod.version,
                                 challenger_model_version=model.version)
    status['generated_at_utc'] = datetime.now(timezone.utc).isoformat()
    status['candidate_activation'] = {'source_tag': source_tag, 'model_sha256': digest,
                                      'production_mutated': False, 'imported_prospective_rows': len(incoming),
                                      'prospective_only': prospective_only,
                                      'quality_status': 'UNVERIFIED_RESEARCH' if prospective_only else 'OFFLINE_EVALUATED'}
    new_shadow = {'shadow_ledger.json': json.dumps(rows, allow_nan=False).encode(),
                  'shadow_report.json': json.dumps(status, allow_nan=False).encode()}
    try:
        checked_publish(candidate, CANDIDATE, fresh, base / 'candidate-readback')
        checked_publish(shadow, SHADOW, new_shadow, base / 'shadow-readback')
        _, unchanged = download(PRODUCTION, base / 'production-readback', MODEL_FILES)
        if unchanged != champion:
            raise RuntimeError('Production changed during candidate-only operation')
    except Exception:
        # Restore BOTH pre-operation bundles even when the first upload failed.
        failures = []
        for store, tag, saved, folder in ((candidate, CANDIDATE, old, 'candidate-rollback'),
                                         (shadow, SHADOW, old_shadow, 'shadow-rollback')):
            try:
                checked_publish(store, tag, saved, base / folder)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError('Rollback readback requires operator recovery: ' + '; '.join(failures))
        raise
    return {'status': 'VERIFIED_ACTIVE_SHADOW_CANDIDATE', 'candidate_version': model.version,
            'candidate_sha256': digest, 'champion_version': prod.version,
            'cohort': status['cohort'], 'production_mutated': False, 'provider_requests': 0,
            'remote_readback': 'VERIFIED', 'source_tag': source_tag}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tag', required=True)
    parser.add_argument('--expected-candidate-sha256', required=True)
    parser.add_argument('--prospective-only', action='store_true')
    parser.add_argument('--expected-source-sha256')
    args = parser.parse_args()
    result = activate(args.source_tag, args.expected_candidate_sha256,
                      prospective_only=args.prospective_only, expected_source_sha=args.expected_source_sha256)
    path = ROOT / '.cache/tbt/candidate-activation-status.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
