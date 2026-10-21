"""Run-bound, SHA-sealed point-in-time frame reused after the full leakage audit.

The cache is only a performance artifact: never a data source or a promotion
certificate. Its content is accepted only with the matching independently
verified full-input backup, same-run identity, and exact hash readback.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from guarded_candidate_backup import validate_certificate

PROFILES = {"standard", "top-7.2.1"}
REQUIRED = {"match_id", "scheduled_at", "target", "tour_atp"}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata_path(path: Path) -> Path:
    return path.with_name(path.name + ".verified.json")


def _assert_frame(frame: pd.DataFrame) -> None:
    if not REQUIRED <= set(frame):
        raise RuntimeError("Audited feature cache lacks required training columns")
    if frame.empty or not frame.match_id.is_unique or frame.match_id.isna().any():
        raise RuntimeError("Audited feature cache identity is invalid")
    if not frame.target.isin((0, 1)).all():
        raise RuntimeError("Audited feature cache targets are invalid")
    times = pd.to_datetime(frame.scheduled_at, utc=True, errors="raise")
    if times.isna().any() or not times.is_monotonic_increasing:
        raise RuntimeError("Audited feature cache chronology is invalid")


def persist(frame: pd.DataFrame, path: str | Path, profile: str) -> dict:
    if profile not in PROFILES:
        raise ValueError("Unknown frozen training profile")
    cert = validate_certificate(require_writer_lock=False)
    _assert_frame(frame)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or _metadata_path(path).exists():
        raise RuntimeError("Refusing to overwrite previously audited feature cache")
    temporary = path.with_suffix(path.suffix + ".part")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    proof = {
        "schema": 1, "training_profile": profile,
        "run_id": cert["run_id"], "attempt": cert["attempt"],
        "application_sha": cert["application_sha"],
        "backup_manifest_sha256": cert["remote_manifest_sha256"],
        "rows": len(frame), "sha256": _sha(path),
    }
    _metadata_path(path).write_text(
        json.dumps(proof, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return proof


def load(path: str | Path, profile: str, matches) -> pd.DataFrame:
    cert = validate_certificate(require_writer_lock=False)
    path = Path(path)
    proof = json.loads(_metadata_path(path).read_text(encoding="utf-8"))
    expected = {
        "schema": 1, "training_profile": profile,
        "run_id": cert["run_id"], "attempt": cert["attempt"],
        "application_sha": cert["application_sha"],
        "backup_manifest_sha256": cert["remote_manifest_sha256"],
    }
    if any(proof.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Feature cache not bound to verified immutable inputs and profile")
    if not path.is_file() or _sha(path) != proof.get("sha256"):
        raise RuntimeError("Feature cache SHA readback mismatch")
    frame = pd.read_parquet(path)
    _assert_frame(frame)
    if len(frame) != proof.get("rows") or len(frame) != len(matches):
        raise RuntimeError("Feature cache match count mismatch")
    # The source itself is independently validated against the backup cert;
    # refuse any cache containing a different set of canonical identities.
    if set(frame.match_id.astype(str)) != {str(m.match_id) for m in matches}:
        raise RuntimeError("Feature cache canonical identity mismatch")
    return frame
