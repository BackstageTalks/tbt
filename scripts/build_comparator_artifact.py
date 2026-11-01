from __future__ import annotations

import argparse
import gzip
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
from release_store import ReleaseStore
from rank_feature_inputs import load_rank_feature_inputs
from tbt.data.atp_leaderboards import ATPLeaderboardPriors
from tbt.data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.wta_rank_history import WTA_RANK_HISTORY_FEATURE_NAMES
from tbt.data.wta_season_stats import WTASeasonPriors
from tbt.models.artifact import load_model
from tbt.services.comparator import build_serving_artifact


ATP_ASSET = "atp_leaderboards_1991_2026_52week_career.csv"
WTA_ASSET = "wta_stats_2010_2026_serving_returning.csv"
COMPARATOR_ASSET = "comparator.json.gz"


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


def _download_required(store: ReleaseStore, names: tuple[str, ...]) -> None:
    store.download(
        extra_names=names,
        required_names=names,
        require_bundle_manifest=True,
    )


def _rank_inputs_required(model) -> bool:
    """Use the same production model feature contract as scripts/pipeline.py."""
    features = set(getattr(model, "feature_names", None) or ())
    return bool(features & (
        set(ATP_RANK_HISTORY_FEATURE_NAMES) | set(WTA_RANK_HISTORY_FEATURE_NAMES)
    ))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Match Comparator serving artifact with zero provider/API calls."
    )
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    args = parser.parse_args()

    cache = ROOT / ".cache" / "tbt" / "comparator-build"
    history_dir = cache / "history"
    model_dir = cache / "model"
    atp_dir = cache / "atp"
    wta_dir = cache / "wta"
    prediction_dir = cache / "predictions"

    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    history_store.download(require_bundle_manifest=True)
    matches = load_partitions(history_dir)
    matches, safety = sanitize_history_identities(matches)
    if safety.get("changed"):
        print(json.dumps({"history_safety": safety}, ensure_ascii=False), flush=True)

    model_store = ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir)
    _download_required(model_store, ("model.joblib", "training_report.json"))
    model = load_model(str(model_dir / "model.joblib"))

    atp_store = ReleaseStore(args.data_repository, "tbt-atp-leaderboards-v1", atp_dir)
    _download_required(atp_store, (ATP_ASSET,))
    atp = ATPLeaderboardPriors.from_csv(atp_dir / ATP_ASSET)

    wta_store = ReleaseStore(args.data_repository, "tbt-wta-season-stats-v1", wta_dir)
    _download_required(wta_store, (WTA_ASSET,))
    wta = WTASeasonPriors.from_csv(wta_dir / WTA_ASSET)

    # Model 7.2.1+ may require point-in-time ATP/WTA weekly ranks. The
    # comparator must load the exact checksum-verified production rank sources
    # used by pipeline.py; a model without these inputs must never publish.
    atp_rank_history = None
    wta_rank_history = None
    rank_report = None
    if _rank_inputs_required(model):
        rank_inputs = load_rank_feature_inputs(
            args.data_repository, cache / "rank-feature-inputs", matches,
        )
        rank_report = rank_inputs.report
        if (rank_report.get("status") != "verified"
                or int(rank_report.get("provider_requests", -1)) != 0):
            raise RuntimeError("Rank inputs failed checksum/zero-provider gate")
        atp_rank_history = rank_inputs.atp
        wta_rank_history = rank_inputs.wta
        print(json.dumps({"comparator_rank_inputs": {
            "status": rank_report["status"],
            "provider_requests": rank_report["provider_requests"],
            "research_release": rank_report["research_release"],
            "wta_crosswalk": rank_report["wta_crosswalk"],
        }}, ensure_ascii=False), flush=True)

    now = datetime.now(timezone.utc)
    artifact = build_serving_artifact(
        model,
        matches,
        now=now,
        atp_leaderboards=atp,
        atp_rank_history=atp_rank_history,
        wta_rank_history=wta_rank_history,
        wta_season_stats=wta,
    )
    artifact = clean(artifact)

    model_version = str((artifact.get("model") or {}).get("model_version") or "")
    if model_version != str(getattr(model, "version", "") or ""):
        raise RuntimeError("Comparator artifact model version does not match production champion")
    source = artifact.get("source") or {}
    if int(source.get("provider_requests_per_user_compare", -1)) != 0:
        raise RuntimeError("Comparator artifact violated zero-provider serving contract")
    if not artifact.get("players"):
        raise RuntimeError("Comparator artifact contains no searchable players")
    if _rank_inputs_required(model) and (
        not isinstance(artifact.get("atp_rank_history"), dict)
        or not isinstance(artifact.get("wta_rank_history"), dict)
    ):
        raise RuntimeError("Missing audited ATP/WTA ranking sources in serving snapshot")

    prediction_store = ReleaseStore(
        args.data_repository,
        "tbt-predictions-v1",
        prediction_dir,
    )
    out = prediction_dir / COMPARATOR_ASSET
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(
            artifact,
            handle,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    # upload_bundle preserves the existing feed/ledger generation and commits
    # checksum coverage for the new comparator asset last.
    prediction_store.upload_bundle([out])

    # Persisted read-back: download the committed release generation into a
    # fresh directory and verify the exact model/cutoff/player count.
    verify_dir = cache / "verify"
    verify_store = ReleaseStore(args.data_repository, "tbt-predictions-v1", verify_dir)
    _download_required(verify_store, (COMPARATOR_ASSET,))
    with gzip.open(verify_dir / COMPARATOR_ASSET, "rt", encoding="utf-8") as handle:
        persisted = json.load(handle)

    persisted_source = persisted.get("source") or {}
    checks = {
        "schema": int(persisted.get("schema") or 0) == 1,
        "model_version": str((persisted.get("model") or {}).get("model_version") or "") == model_version,
        "generated_at": persisted.get("generated_at") == artifact.get("generated_at"),
        "cutoff_utc": persisted.get("cutoff_utc") == artifact.get("cutoff_utc"),
        "players": len(persisted.get("players") or []) == len(artifact.get("players") or []),
        "zero_provider_per_compare": int(persisted_source.get("provider_requests_per_user_compare", -1)) == 0,
        "atp_rank_required_present": not _rank_inputs_required(model) or isinstance(persisted.get("atp_rank_history"), dict),
        "wta_rank_required_present": not _rank_inputs_required(model) or isinstance(persisted.get("wta_rank_history"), dict),
    }
    if not all(checks.values()):
        raise RuntimeError("Persisted comparator read-back failed: " + json.dumps(checks, sort_keys=True))

    print(json.dumps({
        "comparator_build": {
            "status": "verified",
            "provider_api_requests": 0,
            "model_version": model_version,
            "generated_at": artifact.get("generated_at"),
            "cutoff_utc": artifact.get("cutoff_utc"),
            "players": len(artifact.get("players") or []),
            "rank_inputs_verified": bool(rank_report is not None),
            "canonical_matches_replayed": source.get("canonical_matches_replayed"),
            "active_window_days": source.get("active_window_days"),
            "compressed_bytes": out.stat().st_size,
            "persisted_readback": checks,
        }
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
