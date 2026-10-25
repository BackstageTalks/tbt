"""Explicit operator release with a recorded calibration waiver and verified rollback.

No fitting or provider calls. Reuse the existing SHA-addressed champion backup;
never create another archival copy. Caller must hold the global writer lock.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
from _bootstrap import ROOT
from activate_shadow_candidate import download, checked_publish, MODEL_FILES, PRODUCTION, REPO
from verify_champion_rollback import verify_restore, verify_complete_bundle, reference_frame
from tbt.models.artifact import load_model


def release(source_tag, source_sha, champion_sha, reason, request_id, *, override, cache=None):
    if (not re.fullmatch(r'blinq-candidate-frozen-\d+-\d+', source_tag)
            or not all(re.fullmatch(r'[0-9a-f]{64}', s) for s in (source_sha, champion_sha))
            or not re.fullmatch(r'[0-9a-f]{24}', request_id)
            or override is not True or not 10 <= len(reason.strip()) <= 500
            or source_sha == champion_sha):
        raise ValueError('Explicit pinned release and calibration waiver required')
    from cdb_global_writer_lock import verify
    from release_store import _run_gh
    verify(REPO, ROOT / '.cdb-global-writer-lock.json')
    base = Path(cache or ROOT / '.cache/tbt/production-release')
    base.mkdir(parents=True, exist_ok=True)
    backup_tag = 'tbt-champion-backup-sha256-' + champion_sha
    for tag in (source_tag, PRODUCTION, backup_tag):
        if _run_gh(['api', f'repos/{REPO}/releases/tags/{tag}']).returncode:
            raise ValueError('Required existing release/rollback inaccessible: ' + tag)
    source, fresh = download(source_tag, base / 'source', MODEL_FILES)
    production, old = download(PRODUCTION, base / 'production', MODEL_FILES)
    backup, saved = download(backup_tag, base / 'rollback', MODEL_FILES)
    sha = lambda data: hashlib.sha256(data).hexdigest()
    if sha(fresh['model.joblib']) != source_sha or sha(old['model.joblib']) != champion_sha:
        raise ValueError('Model changed after operator approval')
    if saved != old:
        raise ValueError('Existing rollback does not cover the exact serving bundle')
    champion = load_model(str(production.directory / 'model.joblib'))
    verify_restore(production.directory, backup.directory, champion.version)
    model = load_model(str(source.directory / 'model.joblib'))
    report = json.loads(fresh['training_report.json'])
    decision = report.get('promotion_decision') or {}
    if (not model.fitted or not model.feature_names
            or decision.get('candidate_version') != model.version
            or decision.get('production_version') != champion.version
            or not (report.get('evaluation_governance') or {}).get('holdout_fingerprint')):
        raise ValueError('Model schema or evaluated champion provenance mismatch')
    probabilities = np.asarray(model.predict_proba(reference_frame(model.feature_names)), dtype=float)
    if probabilities.size != 3 or not np.isfinite(probabilities).all() or not ((probabilities >= 0) & (probabilities <= 1)).all():
        raise ValueError('Candidate inference smoke test failed')
    audit = dict(schema=1, request_id=request_id, source_tag=source_tag,
                 candidate_version=model.version, previous_version=champion.version,
                 source_sha256=source_sha, previous_sha256=champion_sha,
                 rollback_tag=backup_tag, calibration_override=True, reason=reason.strip(),
                 quality_status='OPERATOR_WAIVED_NOT_VERIFIED',
                 created_at=datetime.now(timezone.utc).isoformat(),
                 run_id=os.environ.get('GITHUB_RUN_ID'), code_sha=os.environ.get('GITHUB_SHA'))
    history = json.loads(old['promotion_history.json'])
    if not isinstance(history, list):
        raise ValueError('Invalid production promotion history')
    fresh['promotion_history.json'] = json.dumps(history + [audit], ensure_ascii=False, allow_nan=False).encode()
    verify(REPO, ROOT / '.cdb-global-writer-lock.json')
    try:
        checked_publish(production, PRODUCTION, fresh, base / 'readback')
        restored = load_model(str(base / 'readback/model.joblib'))
        if restored.version != model.version or not restored.fitted:
            raise ValueError('Production model readback failed')
    except Exception:
        # Restore all serving members even if publication failed part way through.
        checked_publish(production, PRODUCTION, old, base / 'restored')
        # upload_bundle commits a fresh manifest timestamp. Compare all payload
        # bytes and inference, while independently validating the new manifest.
        verify_complete_bundle(base / 'restored')
        recovered = load_model(str(base / 'restored/model.joblib'))
        frame = reference_frame(champion.feature_names)
        if (recovered.version != champion.version or not recovered.fitted
                or not np.allclose(champion.predict_proba(frame), recovered.predict_proba(frame), rtol=0, atol=1e-12)):
            raise RuntimeError('Rollback inference parity failed; manual recovery required')
        raise
    audit.update(status='VERIFIED_PRODUCTION_RELEASE', remote_readback='VERIFIED')
    # Public workflow artifacts/logs omit the private operator rationale.
    public = {key: value for key, value in audit.items() if key != 'reason'}
    (base / 'outcome.json').write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding='utf-8')
    return audit


if __name__ == '__main__':
    result = release(os.environ['SOURCE_TAG'], os.environ['SOURCE_SHA'], os.environ['CHAMPION_SHA'],
                     os.environ['OVERRIDE_REASON'], os.environ['REQUEST_ID'],
                     override=os.environ.get('CALIBRATION_OVERRIDE') == 'true')
    print(json.dumps({key: value for key, value in result.items() if key != 'reason'}, ensure_ascii=False))
