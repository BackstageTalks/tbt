from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from _bootstrap import ROOT
from download_tennis_history import read_json, write_json
from release_store import ReleaseStore
from tbt.models.artifact import load_model
from tbt.services.shadow_evaluation import build_shadow_report


SHADOW_REQUIRED = {"shadow_ledger.json", "shadow_report.json"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize/validate private challenger shadow storage without provider calls"
    )
    parser.add_argument("--data-repository", required=True)
    args = parser.parse_args()

    cache = ROOT / ".cache/tbt"
    production_dir = cache / "shadow-init-production"
    candidate_dir = cache / "shadow-init-candidate"
    shadow_dir = cache / "shadow"

    production_store = ReleaseStore(
        args.data_repository, "tbt-model-production-v1", production_dir
    )
    production_store.download(
        extra_names=("model.joblib",),
        required_names=("model.joblib",),
    )
    production_model = load_model(str(production_dir / "model.joblib"))
    production_version = str(getattr(production_model, "version", "") or "")
    if not production_version:
        raise ValueError("Production model has no version")

    candidate_store = ReleaseStore(
        args.data_repository, "tbt-model-candidate-v1", candidate_dir
    )
    candidate_store.download(
        extra_names=("model.joblib",),
        required_names=("model.joblib",),
    )
    candidate_model = load_model(str(candidate_dir / "model.joblib"))
    challenger_version = str(getattr(candidate_model, "version", "") or "")
    if not challenger_version:
        raise ValueError("Candidate model has no version")

    shadow_store = ReleaseStore(
        args.data_repository, "tbt-model-shadow-v1", shadow_dir
    )
    assets = shadow_store._asset_names()

    if SHADOW_REQUIRED <= assets:
        shadow_store.download(
            extra_names=tuple(sorted(SHADOW_REQUIRED)),
            required_names=tuple(sorted(SHADOW_REQUIRED)),
        )
        ledger = read_json(shadow_dir / "shadow_ledger.json", None)
        report = read_json(shadow_dir / "shadow_report.json", None)
        if not isinstance(ledger, list) or not isinstance(report, dict):
            raise ValueError("Invalid existing shadow release")
        print(json.dumps({
            "shadow_storage": "ready",
            "production_model_version": production_version,
            "challenger_model_version": challenger_version,
            "captured": len(ledger),
        }))
        return

    if assets & SHADOW_REQUIRED:
        raise FileNotFoundError(
            "Incomplete private shadow release; refusing to overwrite partial evidence"
        )

    report = build_shadow_report(
        [],
        production_model_version=production_version,
        challenger_model_version=challenger_version,
    )
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["status"] = (
        "initialized_waiting_for_first_pre_match_snapshot"
        if challenger_version != production_version
        else "disabled_same_model_version"
    )
    write_json(shadow_dir / "shadow_ledger.json", [])
    write_json(shadow_dir / "shadow_report.json", report)
    shadow_store.upload_bundle([
        shadow_dir / "shadow_ledger.json",
        shadow_dir / "shadow_report.json",
    ])
    print(json.dumps({
        "shadow_storage": "initialized",
        "production_model_version": production_version,
        "challenger_model_version": challenger_version,
        "captured": 0,
    }))


if __name__ == "__main__":
    main()
