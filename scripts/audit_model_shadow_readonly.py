"""Read-only, issuance-timestamped champion vs challenger comparison.

Never fits a model, replays an outcome into pre-match features, calls a tennis
provider, or changes a model/CDB/public prediction release. Settlement reflects
the last published private shadow ledger, which may lag latest CDB outcomes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore
from tbt.models.artifact import load_model
from tbt.models.metrics import evaluate_probabilities
from tbt.services.shadow_evaluation import build_shadow_report
from tbt.services.shadow_calibration_research import research_comparison


def _datetime(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Shadow date lacks timezone")
    return d.astimezone(timezone.utc)


def validate_cohort(rows, production_version, challenger_version):
    """Refuse duplicate, after-start, invalid or outcome-mismatched paired rows."""
    seen = set()
    cohort = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid private shadow ledger row")
        if (row.get("production_model_version") != production_version or
                row.get("challenger_model_version") != challenger_version):
            continue
        match_id = str(row.get("match_id") or "")
        if not match_id or match_id in seen:
            raise ValueError("Duplicate/blank match identity in model pair")
        seen.add(match_id)
        captured = _datetime(row.get("captured_at"))
        scheduled = _datetime(row.get("scheduled_at"))
        if captured >= scheduled:
            raise ValueError("Shadow prediction issued after scheduled match start")
        for name in ("production_player1_probability", "challenger_player1_probability"):
            value = float(row[name])
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError("Invalid pre-match model probability")
        if row.get("status") == "settled":
            target = row.get("target_player1_win")
            if type(target) is not int or target not in (0, 1):
                raise ValueError("Invalid settled match outcome")
            for prefix in ("production", "challenger"):
                observed = row.get(prefix + "_correct")
                expected = (float(row[prefix + "_player1_probability"]) >= .5) == bool(target)
                if type(observed) is not bool or observed != expected:
                    raise ValueError("Stored outcome/model prediction disagreement")
        elif row.get("status") not in ("pending", "void", "excluded"):
            raise ValueError("Unrecognized shadow outcome state")
        cohort.append(row)
    return cohort


def _metrics(rows):
    if not rows:
        return {}
    y = [int(r["target_player1_win"]) for r in rows]
    def single(key):
        result = evaluate_probabilities(y, (r[key] for r in rows))
        return {name: (round(value, 8) if isinstance(value, (int, float))
                        and math.isfinite(value) else None)
                for name, value in result.items()
                if name in ("n", "accuracy", "brier_score", "log_loss", "ece_10", "roc_auc")}
    return {"champion": single("production_player1_probability"),
            "challenger": single("challenger_player1_probability")}


def summarize(rows, production_version, challenger_version, source_ts=None):
    if production_version == challenger_version:
        raise ValueError("Challenger is identical to champion")
    cohort = validate_cohort(rows, production_version, challenger_version)
    summary = build_shadow_report(
        cohort, production_model_version=production_version,
        challenger_model_version=challenger_version,
    )
    settled = [r for r in cohort if r["status"] == "settled"]
    segments = {}
    for field in ("tour", "surface"):
        segments[field] = {}
        for label in sorted({str(r.get(field) or "unknown") for r in settled}):
            segment = [r for r in settled if str(r.get(field) or "unknown") == label]
            if len(segment) >= 30:
                segments[field][label] = _metrics(segment)
    last_capture = max((str(r["captured_at"]) for r in cohort), default=None)
    return {
        "schema": 1,
        "status": ("EVALUATED" if len(settled) >= 200 and summary["cohort"]["settled_utc_days"] >= 3
                   else "INSUFFICIENT_PAIRED_SAMPLE"),
        "source_shadow_last_generated_at": source_ts,
        "last_pre_match_capture": last_capture,
        "production_model_version": production_version,
        "challenger_model_version": challenger_version,
        "cohort": summary["cohort"],
        "overall": _metrics(settled),
        "paired": summary["paired"],
        "calibration_research": research_comparison(cohort, production_version, challenger_version),
        "gate": summary["gate"],
        "segments": segments,
        "roi_yield_status": "NOT_EVALUABLE_WITHOUT_VERIFIED_PREMATCH_ODDS",
        "limits": [
            "No retraining or modification of model artifacts, CDB or public predictions.",
            "Settlements reflect the last private shadow ledger update, not independently refreshed outcomes.",
            "Comparison uses identical originally issued matches; sample size and age must be considered.",
            "The shadow test does not establish incremental benefit of today's CDB imports.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--out", type=Path, default=ROOT / ".cache/tbt/model-shadow-audit/report.json")
    args = parser.parse_args()
    if not os.environ.get("GH_TOKEN"):
        parser.error("Private release read token unavailable")
    root = ROOT / ".cache/tbt/model-shadow-audit"
    production = ReleaseStore(args.data_repository, "tbt-model-production-v1", root / "production")
    candidate = ReleaseStore(args.data_repository, "tbt-model-candidate-v1", root / "candidate")
    shadow = ReleaseStore(args.data_repository, "tbt-model-shadow-v1", root / "shadow")
    production.download(required_names=("model.joblib", "training_report.json"),
                        require_bundle_manifest=True)
    candidate.download(required_names=("model.joblib",), require_bundle_manifest=True)
    shadow.download(required_names=("shadow_ledger.json", "shadow_report.json"),
                    require_bundle_manifest=True)
    champion = load_model(str(production.directory / "model.joblib"))
    challenger = load_model(str(candidate.directory / "model.joblib"))
    if not champion.fitted or not challenger.fitted:
        raise ValueError("Unfitted model artifact")
    ledger = json.loads((shadow.directory / "shadow_ledger.json").read_text())
    previous = json.loads((shadow.directory / "shadow_report.json").read_text())
    if not isinstance(ledger, list) or not isinstance(previous, dict):
        raise ValueError("Malformed shadow release")
    result = summarize(
        ledger, str(champion.version), str(challenger.version),
        source_ts=previous.get("generated_at_utc"),
    )
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["sources"] = {
        "champion_sha256": sha256((production.directory / "model.joblib").read_bytes()).hexdigest(),
        "challenger_sha256": sha256((candidate.directory / "model.joblib").read_bytes()).hexdigest(),
        "shadow_ledger_sha256": sha256((shadow.directory / "shadow_ledger.json").read_bytes()).hexdigest(),
        "release_tags": ["tbt-model-production-v1", "tbt-model-candidate-v1", "tbt-model-shadow-v1"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False, sort_keys=True) + "\n")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
