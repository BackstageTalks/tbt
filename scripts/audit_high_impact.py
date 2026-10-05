"""Read-only production-model and causal feature audit. No tennis API calls.

Importance is descriptive permutation sensitivity on post-training data, not a
candidate promotion test. Zero differences are not interpreted as missing data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gc
import json
from pathlib import Path

import numpy as np
import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from audit_environment_release import download_committed_history, _coverage
from audit_statistics_inventory import build as statistics_inventory
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder, FEATURE_NAMES
from tbt.services.data_quality import audit_history


def calibration_buckets(probabilities, targets):
    """Calibration of the selected side, including exact 50/100% boundaries."""
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(targets, dtype=int)
    confidence = np.maximum(p, 1 - p)
    correct = (p >= .5) == y
    out = []
    edges = [.5, .55, .6, .65, .7, .8, 1.0]
    for lo, hi in zip(edges, edges[1:]):
        mask = (confidence >= lo) & ((confidence <= hi) if hi == 1 else (confidence < hi))
        n = int(mask.sum())
        out.append({"from": lo, "to": hi, "n": n,
                    "mean_confidence": float(confidence[mask].mean()) if n else None,
                    "actual_win_rate": float(correct[mask].mean()) if n else None,
                    "brier": float(np.mean((confidence[mask] - correct[mask]) ** 2)) if n else None})
    return out


def coverage(frame):
    """Report actual availability flags; a zero feature value can be observed."""
    flags = [name for name in frame if "known" in name]
    return {"rows": len(frame), "availability": {
        name: {"observed_rows": int((frame[name] > 0).sum()),
               "observed_rate": float((frame[name] > 0).mean()) if len(frame) else None}
        for name in flags}}


def metrics(p, y):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    y = np.asarray(y, dtype=int)
    n = len(y)
    return {"n": n, "accuracy": float(np.mean((p >= .5) == y)) if n else None,
            "brier": float(np.mean((p - y) ** 2)) if n else None,
            "log_loss": float(-np.mean(y * np.log(p) + (1-y) * np.log(1-p))) if n else None,
            "calibration": calibration_buckets(p, y)}


def fitted_model_boundary(metadata):
    """Exclude calibration/selection as well as the base training interval.

    history_end alone is insufficient: a fixed ensemble can fit its calibrator
    and choose blends on months after its base classifier training cutoff.
    """
    required = ('history_end', 'trained_at')
    dates = {}
    for name in (*required, 'evaluation_end', 'calibration_end'):
        value = metadata.get(name)
        if value is None and name not in required:
            continue
        date = pd.to_datetime(value, utc=True, errors='coerce')
        if pd.isna(date):
            raise ValueError(f'Production {name} missing/invalid: cannot declare a post-fitting audit')
        dates[name] = date
    return max(dates.values())


def main():
    from tbt.models.artifact import load_model
    from tbt.services.training import _enforce_rank_provenance

    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/high-impact/report.json")
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    history_dir = out.parent / "history"
    store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    download_committed_history(store, history_dir)
    raw = load_partitions(history_dir)
    raw, identity = sanitize_history_identities(raw)
    accepted, quality = audit_history(raw)
    inventory = statistics_inventory(accepted)
    environment = _coverage(accepted)
    rank_sources = Counter()
    for match in accepted:
        provenance = (match.provider_payload or {}).get("_tbt_rank_provenance") or {}
        rank_sources[str(provenance.get("source") or "missing")] += 1
    cleaned, ranks = _enforce_rank_provenance(accepted)
    del raw, accepted
    gc.collect()
    print(json.dumps({"phase": "history", "accepted": len(cleaned)}), flush=True)
    frame = FeatureBuilder().build_training_frame(cleaned)
    del cleaned
    gc.collect()
    frame["year"] = pd.to_datetime(frame.scheduled_at, utc=True).dt.year
    model_dir = out.parent / "model"
    production = ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir)
    production.download(extra_names=("model.joblib", "training_report.json"),
                        required_names=("model.joblib", "training_report.json"))
    model = load_model(str(model_dir / "model.joblib"))
    cutoff = fitted_model_boundary(model.metadata)
    # Whole-day isolation matches the production training/evaluation contract.
    eligible = frame.loc[pd.to_datetime(frame.scheduled_at, utc=True).dt.normalize() > cutoff.normalize()].copy()
    report = {"schema": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
              "provider_requests": 0, "production_mutated": False,
              "history_quality": quality, "identity": identity,
              "rank_provenance": ranks, "rank_sources": dict(rank_sources),
              "statistics_inventory": inventory, "environment": environment,
              "history_manifest": json.loads((history_dir / "history_manifest.json").read_text()),
              "model": {"version": model.version, "metadata": model.metadata,
                        "features": model.feature_names,
                        "masked_features": sorted(model.excluded_features),
                        "unused_generated_features": sorted(set(FEATURE_NAMES)-set(model.feature_names))},
              "causal_coverage": {"overall": coverage(frame),
                  "by_tour": {str(k): coverage(g) for k, g in frame.groupby("tour")},
                  "by_year": {str(k): coverage(g) for k, g in frame.groupby("year")},
                  "by_tour_recent": {str(k): coverage(g) for k, g in frame.loc[frame.year >= 2023].groupby("tour")}},
              "feature_values": {name: {"nonfinite": int((~np.isfinite(frame[name])).sum()),
                                        "zero_rate": float((frame[name] == 0).mean()),
                                        "standard_deviation": float(frame[name].std())}
                                 for name in model.feature_names},
              "evaluation_boundary": str(cutoff),
              "evaluation_policy": "Whole UTC days after all recorded fitting/calibration/evaluation boundaries and model availability; descriptive audit, never an automatic promotion or tuning gate."}
    if len(eligible):
        predictions = model.predict_proba(eligible)
        eligible["audit_probability"] = predictions
        report["post_training"] = {"overall": metrics(predictions, eligible.target),
            "by_tour": {str(k): metrics(g.audit_probability, g.target) for k,g in eligible.groupby("tour")},
            "by_surface": {str(k): metrics(g.audit_probability, g.target) for k,g in eligible.groupby("surface")},
            "by_data_depth": {str(k): metrics(g.audit_probability, g.target) for k,g in eligible.groupby(pd.cut(eligible.data_depth, [-.01,.5,.75,.9,1.01]))}}
        # Deterministic recent sample; paired shuffling preserves tour-specific
        # feature distributions. Sensitivity is not causal feature benefit.
        sample = eligible.sort_values("scheduled_at").tail(20000).sample(n=min(4000,len(eligible)), random_state=42)
        baseline = metrics(model.predict_proba(sample), sample.target)
        rng = np.random.default_rng(42)
        importance = []
        for name in model.feature_names:
            if name in model.excluded_features:
                continue
            changed = sample.copy()
            for _, idx in changed.groupby("tour").groups.items():
                changed.loc[idx,name] = rng.permutation(changed.loc[idx,name].to_numpy())
            perturbed = metrics(model.predict_proba(changed), sample.target)
            importance.append({"feature": name,
                "delta_log_loss": perturbed["log_loss"]-baseline["log_loss"],
                "delta_brier": perturbed["brier"]-baseline["brier"],
                "delta_accuracy": perturbed["accuracy"]-baseline["accuracy"]})
        report["permutation_sensitivity"] = {"n":len(sample), "baseline":baseline,
             "method":"Single within-tour permutation; correlated features and known flags can reduce interpretation reliability. Descriptive only.",
             "features":sorted(importance,key=lambda x:x["delta_log_loss"],reverse=True)}
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding="utf-8")
    print(json.dumps({"phase":"complete","rows":len(frame),"post_training_rows":len(eligible),"model":model.version}),flush=True)


if __name__ == "__main__":
    main()
