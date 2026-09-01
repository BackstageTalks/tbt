from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT
from tbt.config import settings
from tbt.models.artifact import save_model
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.training import train_from_matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Train calibrated TBT v200 model from Supabase history")
    parser.add_argument("--output", default=settings.model_artifact)
    parser.add_argument("--min-matches", type=int, default=settings.min_train_matches)
    parser.add_argument("--report", default=str(ROOT / "reports" / "training.json"))
    args = parser.parse_args()

    repo = SupabaseRepository()
    matches = repo.get_completed_matches()
    result = train_from_matches(matches, min_matches=args.min_matches)
    save_model(result.model, args.output)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result.report, indent=2, default=str), encoding="utf-8")

    if settings.supabase_write_key:
        md = result.model.metadata
        repo.save_model_version(
            {
                "model_version": result.model.version,
                "history_start": md.get("history_start"),
                "history_end": md.get("history_end"),
                "training_matches": md.get("training_matches"),
                "holdout_metrics": md.get("holdout_metrics"),
                "metadata": md,
            }
        )
    print(json.dumps({"artifact": args.output, "model_version": result.model.version, **result.report}, indent=2, default=str))


if __name__ == "__main__":
    main()
