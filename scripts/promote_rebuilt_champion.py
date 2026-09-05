from __future__ import annotations

import argparse
import json
from pathlib import Path

from tbt.models.artifact import load_model
from tbt.repositories.supabase import SupabaseRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote a freshly rebuilt V3 model artifact to Supabase champion registry"
    )
    parser.add_argument("--file", required=True)
    parser.add_argument(
        "--reason",
        default="V20.8 explicit rebuild from private GitHub history after storage migration",
    )
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Model artifact missing or empty: {path}")

    model = load_model(str(path))
    version = str(getattr(model, "version", "") or "")
    if not version:
        raise SystemExit("Rebuilt model artifact has no model version")
    if int(getattr(model, "artifact_version", 0) or 0) < 3:
        raise SystemExit("Rebuilt model is not a V3 checkpoint artifact")
    if not getattr(model, "feature_state", None):
        raise SystemExit("Rebuilt model has no feature-state checkpoint")
    if not getattr(model, "feature_state_cutoff", None):
        raise SystemExit("Rebuilt model has no feature-state cutoff")

    repo = SupabaseRepository()
    challenger = repo.latest_challenger_model_version()
    if not challenger:
        raise SystemExit("No challenger is registered in Supabase")
    challenger_version = str(challenger.get("model_version") or "")
    if challenger_version != version:
        raise SystemExit(
            f"Latest challenger mismatch: artifact={version!r}, registry={challenger_version!r}"
        )

    result = repo.promote_model(version, reason=args.reason)
    champion = repo.champion_model_version()
    champion_version = str((champion or {}).get("model_version") or "")
    if champion_version != version:
        raise SystemExit(
            f"Promotion verification failed: expected={version!r}, champion={champion_version!r}"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "model_version": version,
                "artifact_version": int(getattr(model, "artifact_version", 0) or 0),
                "feature_state_cutoff": getattr(model, "feature_state_cutoff", None),
                "lifecycle_status": (champion or {}).get("lifecycle_status"),
                "promotion_result": result,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
