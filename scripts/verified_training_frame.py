"""Run-bound, SHA-sealed point-in-time frame reused after the full leakage audit.

The cache is only a performance artifact: never a data source or a promotion
certificate. Its content is accepted only with the matching independently
verified full-input backup, same-run identity, and exact hash readback.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from guarded_candidate_backup import validate_certificate
from tbt.services.data_quality import audit_history

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


def persist(frame: pd.DataFrame, path: str | Path, profile: str, *, audit_at: datetime | None = None) -> dict:
    if profile not in PROFILES:
        raise ValueError("Unknown frozen training profile")
    cert = validate_certificate(require_writer_lock=False)
    _assert_frame(frame)
    if audit_at is not None and (audit_at.tzinfo is None or audit_at.utcoffset() is None):
        raise ValueError("Naive history audit timestamp")
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
        # Stable cutoff is bound to this run's SHA-checked cohort proof.
        "history_audit_at": audit_at.isoformat() if audit_at is not None else None,
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
    if len(frame) != proof.get("rows"):
        raise RuntimeError("Feature cache match count mismatch")
    # Leakage audit stores the point-in-time feature frame for the accepted
    # completed match cohort, NOT all raw CDB rows. Reconstruct that exact
    # quality-filtered cohort from the same immutable inputs. Comparing against
    # raw counts falsely rejected valid caches whenever cancelled/future/
    # invalid rows were present; bypassing this identity gate would be unsafe.
    frozen_at = proof.get("history_audit_at")
    try:
        audit_at = datetime.fromisoformat(frozen_at) if frozen_at is not None else None
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid frozen history audit timestamp") from exc
    if audit_at is not None and (audit_at.tzinfo is None or audit_at.utcoffset() is None):
        raise RuntimeError("Naive frozen history audit timestamp")
    accepted, _ = audit_history(matches, now=audit_at)
    if len(frame) != len(accepted):
        raise RuntimeError("Feature cache audited match count mismatch")
    if set(frame.match_id.astype(str)) != {str(m.match_id) for m in accepted}:
        raise RuntimeError("Feature cache canonical identity mismatch")
    if audit_at is not None:
        # Propagate the same verified cutoff through training, without trusting
        # unverified DataFrame attrs to survive a Parquet round trip.
        frame.attrs["history_audit_at"] = audit_at.isoformat()
    return frame
