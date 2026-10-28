"""Read-only, current production TOP accuracy from originally issued private offers.

No tennis provider calls, CDB writes, model training or serving promotion.
Only exact pre-deploy confirmed model-version + bookmaker price evidence counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from _bootstrap import ROOT
from audit_top_reliability import analyze
from release_store import ReleaseStore
from tbt.models.artifact import load_model

DATA_REPOSITORY = "BackstageTalks/tbt-data"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_report(repo: str = DATA_REPOSITORY, *, directory: Path | None = None) -> dict:
    if repo != DATA_REPOSITORY:
        raise ValueError("Unexpected canonical data repository")
    root = Path(directory or ROOT / ".cache/tbt/current-production-top")
    pred = ReleaseStore(repo, "tbt-predictions-v1", root / "predictions")
    pred.download(
        extra_names=("ledger.json",), required_names=("ledger.json",),
        require_bundle_manifest=True,
    )
    path = pred.directory / "ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(ledger, list):
        raise ValueError("Invalid immutable production publication ledger")

    prod = ReleaseStore(repo, "tbt-model-production-v1", root / "production")
    prod.download(
        extra_names=("model.joblib",), required_names=("model.joblib",),
        require_bundle_manifest=True,
    )
    model_path = prod.directory / "model.joblib"
    active = load_model(str(model_path))
    if not active.fitted or not active.version:
        raise ValueError("Production model read-back invalid")

    result = analyze(ledger, model_version=active.version, window_days=30)
    summary = result["overall"]
    return {
        "schema": 1,
        "status": ("DESCRIPTIVE_ISSUED_COHORT" if summary["settled"] >= 30
                   else "INSUFFICIENT_CURRENT_MODEL_SETTLED_TOP"),
        "production_version": active.version,
        "production_model_sha256": _sha(model_path),
        "publication_ledger_sha256": _sha(path),
        "window_days": 30,
        "overall": summary,
        "diagnostics": result["diagnostics"],
        "coverage": result["coverage"],
        "subgroups": {
            "competition": result["subgroups"]["competition"],
            "confidence_band": result["subgroups"]["confidence_band"],
            "surface_evidence": result["subgroups"]["surface_evidence"],
        },
        "limits": [
            "Only original TOP publications whose model version is independently "
            "confirmed against the active production model binary.",
            "Exact two-way quoted bookmaker odds and saved pre-deploy issuance required.",
            "Published selections are unchanged. No historical counterfactual or "
            "claim that losing picks could have been profitably replaced.",
            "Evaluation uses the private settled publication result; canonical "
            "settlement identity and missing outcomes are audited separately.",
        ],
        "provider_requests": 0,
        "CDB_mutated": False,
        "production_mutated": False,
        "model_promoted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".cache/tbt/current-production-top/report.json")
    args = parser.parse_args()
    result = current_report()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    # Aggregate only: never print private event/player/odds rows.
    print(json.dumps({
        "status": result["status"],
        "model_version": result["production_version"],
        "settled": result["overall"]["settled"],
        "published": result["overall"]["published"],
        "wins": result["overall"]["wins"],
        "losses": result["overall"]["losses"],
        "hit_rate": result["overall"]["hit_rate"],
        "brier": result["overall"]["brier"],
        "yield_flat_stake": result["overall"]["yield_flat_stake"],
        "diagnostics": result["diagnostics"],
        "provider_requests": 0,
        "CDB_mutated": False,
        "production_mutated": False,
    }, allow_nan=False))


if __name__ == "__main__":
    main()
