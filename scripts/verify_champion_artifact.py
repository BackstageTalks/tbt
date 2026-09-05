from __future__ import annotations

import argparse
import json

from tbt.models.artifact import load_model
from tbt.repositories.supabase import SupabaseRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a local model artifact against the Supabase champion registry")
    parser.add_argument("--file", required=True)
    parser.add_argument("--require-state", action="store_true")
    args = parser.parse_args()

    model = load_model(args.file)
    champion = SupabaseRepository().champion_model_version()
    if not champion:
        raise SystemExit("No champion model is registered in Supabase")

    champion_version = str(champion.get("model_version") or "")
    artifact_version = str(getattr(model, "version", "") or "")
    if artifact_version != champion_version:
        raise SystemExit(
            f"Champion mismatch: artifact={artifact_version!r}, registry={champion_version!r}"
        )

    has_state = bool(getattr(model, "feature_state", None))
    cutoff = getattr(model, "feature_state_cutoff", None)
    artifact_schema = int(getattr(model, "artifact_version", 0) or 0)
    if args.require_state and (artifact_schema < 3 or not has_state or not cutoff):
        raise SystemExit(
            "Champion artifact has no V3 feature-state checkpoint; refusing egress-unsafe production refresh"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "model_version": artifact_version,
                "artifact_version": artifact_schema,
                "has_feature_state": has_state,
                "feature_state_cutoff": cutoff,
                "lifecycle_status": champion.get("lifecycle_status"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
