"""Verify a SHA-addressed backup of the exact serving champion in isolation.

READ-ONLY with respect to serving production/candidate releases and all CDB
data. GitHub workflow manages a separate, never-clobbered backup release.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.models.artifact import load_model


BUNDLE = ("model.joblib", "training_report.json", "promotion_history.json")
MANIFEST = "_tbt_bundle_manifest.json"


def hash_file(path: Path) -> str:
    d = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def verify_complete_bundle(directory: Path) -> dict:
    """Require all four exact files, verified SHA-256 and no extra manifest assets."""
    path = directory / MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Invalid production bundle manifest schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(BUNDLE):
        raise ValueError("Missing/extra committed serving artifact")
    result = {}
    for name in BUNDLE:
        item = files[name]
        p = directory / name
        if not isinstance(item, dict) or not p.is_file():
            raise ValueError("Missing serving bundle member: " + name)
        actual = {"sha256": hash_file(p), "bytes": p.stat().st_size}
        if actual != {"sha256": item.get("sha256"), "bytes": item.get("bytes")}:
            raise ValueError("Serving bundle manifest hash or size mismatch: " + name)
        result[name] = actual
    result[MANIFEST] = {"sha256": hash_file(path), "bytes": path.stat().st_size}
    return result


def reference_frame(names: list[str]) -> pd.DataFrame:
    """Fixed, outcome-free replay probes; used for RESTORE parity, not accuracy."""
    rows = []
    for offset in (0.0, 0.07, -0.03):
        row = {name: 0.0 for name in names}
        for name in ("elo_probability", "season_yelo_probability"):
            if name in row:
                row[name] = 0.52 + offset
        if "tour_atp" in row:
            row["tour_atp"] = 1.0
        if "data_depth" in row:
            row["data_depth"] = 0.65
        if "rank_known_both" in row:
            row["rank_known_both"] = 1.0
        rows.append(row)
    return pd.DataFrame(rows, columns=names)


def verify_restore(source: Path, restored: Path, expected_version: str) -> dict:
    before, after = verify_complete_bundle(source), verify_complete_bundle(restored)
    if before != after:
        raise ValueError("Restored champion bytes differ from source")
    live = load_model(str(source / "model.joblib"))
    recovered = load_model(str(restored / "model.joblib"))
    if (not live.fitted or not recovered.fitted
            or live.version != expected_version or recovered.version != expected_version
            or live.feature_names != recovered.feature_names
            or live.metadata != recovered.metadata
            or live.artifact_version != recovered.artifact_version):
        raise ValueError("Serving model version, fit state, schema or metadata mismatch")
    frame = reference_frame(live.feature_names)
    original = np.asarray(live.predict_proba(frame), dtype=np.float64)
    replay = np.asarray(recovered.predict_proba(frame), dtype=np.float64)
    if not (len(original) == 3 and np.isfinite(original).all()
            and np.isfinite(replay).all()
            and np.allclose(original, replay, rtol=0, atol=1e-12)):
        raise ValueError("Isolated champion restore prediction parity FAILED")
    return {
        "schema": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "expected_champion_version": expected_version,
        "restored_version": recovered.version,
        "artifact_version": recovered.artifact_version,
        "feature_count": len(recovered.feature_names),
        "model_fitted": True,
        "parity_samples": len(original),
        "max_prediction_difference": float(np.max(np.abs(original - replay))),
        "reference_predictions": [float(x) for x in original],
        "bundle_files": before,
        "production_mutated": False,
        "candidate_mutated": False,
        "canonical_mutated": False,
        "provider_requests": 0,
        "test_purpose": "isolated rollback byte/inference parity, not candidate promotion",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--restored", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--backup-tag", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = verify_restore(args.source, args.restored, args.expected_version)
    model_hash = report["bundle_files"]["model.joblib"]["sha256"]
    if args.backup_tag != "tbt-champion-backup-sha256-" + model_hash:
        parser.error("Backup tag is not the exact champion's content digest")
    report["backup_tag"] = args.backup_tag
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "bundle_files"}, sort_keys=True))


if __name__ == "__main__":
    main()
