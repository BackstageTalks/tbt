"""Forensic inspection of frozen production model calibration only; no fitting.

Checks whether the exact probability seen for different opponents is a
legitimate repeated output plateau of a frozen isotonic calibrator. This is
not a point-in-time replay of either historical match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np

from tbt.models.artifact import load_model

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-model-production-v1"
TARGET = 0.8304140127388535


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def run(destination: Path):
    release = json.loads(gh("api", f"repos/{REPO}/releases/tags/{TAG}"))
    assets = {a["name"]: a for a in release.get("assets", [])}
    asset = assets.get("model.joblib")
    if not asset or not asset.get("digest"):
        raise RuntimeError("Model artifact missing release digest")
    destination.mkdir(parents=True, exist_ok=True)
    before = (asset["id"], asset["size"], asset["digest"])
    gh("release", "download", TAG, "--repo", REPO, "--pattern", "model.joblib",
       "--dir", str(destination), "--clobber")
    path = destination / "model.joblib"
    blob = path.read_bytes()
    actual = "sha256:" + hashlib.sha256(blob).hexdigest()
    after_assets = {
        a["name"]: a for a in json.loads(
            gh("api", f"repos/{REPO}/releases/tags/{TAG}")
        ).get("assets", [])
    }
    after = after_assets["model.joblib"]
    if before != (after["id"], after["size"], after["digest"]) or len(blob) != asset["size"] or actual != asset["digest"]:
        raise RuntimeError("Production model artifact changed or digest mismatch")
    model = load_model(str(path))
    if not model.fitted:
        raise RuntimeError("Production model is unfitted")
    out = {
        "model_version": model.version,
        "model_sha256": actual.removeprefix("sha256:"),
        "trained_feature_count": len(model.feature_names),
        "model_objective": model.objective,
        "blend_weight": model.blend_weight,
        "elo_weight": model.elo_weight,
        "atp_blend_weight": getattr(model, "atp_blend_weight", None),
        "atp_elo_weight": getattr(model, "atp_elo_weight", None),
        "calibrators": {},
        "reproduced_target_from_calibration_curve": False,
        "point_in_time_match_features_available": False,
        "model_retrained": False,
        "model_promoted": False,
        "CDB_mutated": False,
        "provider_requests": 0,
    }
    for key, cal in (("global", model.calibrator), ("atp", (getattr(model, "tour_calibrators", {}) or {}).get("atp")),
                     ("wta", (getattr(model, "tour_calibrators", {}) or {}).get("wta"))):
        if cal is None:
            out["calibrators"][key] = {"kind": "not_present"}
            continue
        kind = cal.kind
        info = {"kind": kind}
        if kind == "isotonic" and cal.model is not None:
            thresholds = getattr(cal.model, "X_thresholds_", [])
            y = getattr(cal.model, "y_thresholds_", [])
            info["n_calibration_knots"] = len(thresholds)
            info["distinct_step_values"] = len(set(map(float, y)))
        raw = np.linspace(0.501, 0.989, 10000)
        calibrated = model._calibrated(cal, raw)
        repeats = np.isclose(calibrated, TARGET, atol=1e-13, rtol=0)
        info["target_plateau_exact_matches_on_grid"] = int(repeats.sum())
        if repeats.any():
            info["target_raw_probability_min"] = float(raw[repeats].min())
            info["target_raw_probability_max"] = float(raw[repeats].max())
        out["calibrators"][key] = info
        if key in ("atp", "global") and repeats.any():
            out["reproduced_target_from_calibration_curve"] = True
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--cache", default=".cache/safonov-model")
    args = p.parse_args()
    result = run(Path(args.cache))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
