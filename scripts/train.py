from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from tbt.config import settings
from tbt.data.history_source import default_history_dir, load_training_history
from tbt.models.artifact import save_model
from tbt.models.feature_builder import FeatureBuilder
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.training import train_from_matches


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train calibrated TBT challenger model from private GitHub history partitions"
    )
    parser.add_argument("--output", default=settings.model_artifact)
    parser.add_argument("--min-matches", type=int, default=settings.min_train_matches)
    parser.add_argument("--report", default=str(ROOT / "reports" / "training.json"))
    parser.add_argument(
        "--history-dir",
        default=str(default_history_dir(ROOT)),
        help="Directory containing history-YYYY.parquet assets downloaded from tbt-data",
    )
    parser.add_argument(
        "--skip-registry-write",
        action="store_true",
        help="Build/evaluate the challenger without writing model_versions (diagnostic only).",
    )
    args = parser.parse_args()

    matches = load_training_history(args.history_dir, root=ROOT)
    result = train_from_matches(matches, min_matches=args.min_matches)

    # Runtime predictions must preserve the complete historical Elo/form/H2H state
    # even after 2021-2024 rows are deleted from Supabase.  The checkpoint lives in
    # the model artifact and only post-cutoff hot results are replayed later.
    latest_history = max(match.scheduled_at for match in matches)
    try:
        overlap_days = int(os.getenv("TBT_HOT_RETENTION_DAYS", "60"))
    except ValueError:
        overlap_days = 60
    retention_days = min(max(overlap_days, 14), 180)
    # Keep the checkpoint *inside* the rolling Supabase hot window, not at its
    # oldest edge.  This leaves an overlap margin so clock drift, ingestion lag,
    # or a restore performed a day or two later cannot create a silent replay gap.
    try:
        checkpoint_overlap_days = int(os.getenv("TBT_CHECKPOINT_OVERLAP_DAYS", "14"))
    except ValueError:
        checkpoint_overlap_days = 14
    checkpoint_overlap_days = min(max(checkpoint_overlap_days, 3), retention_days - 1)
    checkpoint_age_days = retention_days - checkpoint_overlap_days
    generated_at = datetime.now(timezone.utc)
    rolling_cutoff = generated_at - timedelta(days=checkpoint_age_days)
    cutoff = min(latest_history, rolling_cutoff)
    replay = FeatureBuilder()
    replay.replay(matches, before=cutoff)
    md = dict(result.model.metadata or {})
    md["history_source"] = "private GitHub Release year partitions + rolling Supabase delta"
    md["feature_state_cutoff"] = cutoff.astimezone(timezone.utc).isoformat()
    md["feature_state_generated_at"] = generated_at.isoformat()
    md["feature_state_artifact_version"] = 3
    md["feature_state_hot_retention_days"] = retention_days
    md["feature_state_overlap_days"] = checkpoint_overlap_days
    result.model.metadata = md

    # Save only after metadata is final so the artifact and registry describe the
    # exact same model/data checkpoint.
    save_model(
        result.model,
        args.output,
        feature_state=replay.export_state(),
        feature_state_cutoff=cutoff,
        feature_state_generated_at=generated_at,
    )

    report = dict(result.report)
    report["history_source"] = "private GitHub Release year partitions + rolling Supabase delta"
    report["history_rows_loaded"] = len(matches)
    report["feature_state_cutoff"] = cutoff.astimezone(timezone.utc).isoformat()
    report["feature_state_hot_retention_days"] = retention_days
    report["feature_state_overlap_days"] = checkpoint_overlap_days

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    if settings.supabase_write_key and not args.skip_registry_write:
        repo = SupabaseRepository()
        repo.save_model_version(
            {
                "model_version": result.model.version,
                "history_start": md.get("history_start"),
                "history_end": md.get("history_end"),
                "training_matches": md.get("training_matches"),
                "holdout_metrics": md.get("holdout_metrics"),
                "metadata": md,
                "lifecycle_status": "challenger",
                "promoted_at": None,
                "rejected_at": None,
                "promotion_reason": None,
            }
        )

    print(
        json.dumps(
            {
                "artifact": args.output,
                "model_version": result.model.version,
                "lifecycle_status": "challenger",
                "registry_write_skipped": bool(args.skip_registry_write),
                **report,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
