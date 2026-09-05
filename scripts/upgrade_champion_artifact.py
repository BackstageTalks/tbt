from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from tbt.data.history_source import default_history_dir, load_training_history
from tbt.models.artifact import load_model, save_model
from tbt.models.feature_builder import FeatureBuilder


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Upgrade an existing champion model artifact to V3 by embedding the "
            "full historical FeatureBuilder replay checkpoint. Model weights/version stay unchanged."
        )
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--history-dir", default=str(default_history_dir(ROOT)))
    args = parser.parse_args()

    model = load_model(args.input)
    matches = load_training_history(args.history_dir, root=ROOT)
    if not matches:
        raise SystemExit("No history available for feature-state checkpoint")

    latest_history = max(match.scheduled_at for match in matches)
    overlap_days = 60
    cutoff = latest_history - timedelta(days=overlap_days)
    builder = FeatureBuilder()
    builder.replay(matches, before=cutoff)
    generated_at = datetime.now(timezone.utc)

    md = dict(getattr(model, "metadata", {}) or {})
    md.update(
        {
            "history_source": "private GitHub Release yearly Parquet partitions",
            "feature_state_cutoff": cutoff.astimezone(timezone.utc).isoformat(),
            "feature_state_generated_at": generated_at.isoformat(),
            "feature_state_artifact_version": 3,
            "feature_state_overlap_days": overlap_days,
            "artifact_upgrade": "weights/version unchanged; runtime replay checkpoint added",
        }
    )
    model.metadata = md

    save_model(
        model,
        args.output,
        feature_state=builder.export_state(),
        feature_state_cutoff=cutoff,
        feature_state_generated_at=generated_at,
    )

    upgraded = load_model(args.output)
    if str(getattr(upgraded, "version", "")) != str(getattr(model, "version", "")):
        raise SystemExit("Model version changed during artifact upgrade")
    if int(getattr(upgraded, "artifact_version", 0)) < 3:
        raise SystemExit("Artifact upgrade did not produce V3")
    if not getattr(upgraded, "feature_state", None):
        raise SystemExit("Artifact upgrade produced no feature state")

    print(
        json.dumps(
            {
                "model_version": upgraded.version,
                "artifact_version": upgraded.artifact_version,
                "history_rows": len(matches),
                "feature_state_cutoff": upgraded.feature_state_cutoff,
                "feature_state_overlap_days": overlap_days,
                "weights_changed": False,
                "output": str(Path(args.output)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
