from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from tbt.models.artifact import load_model
from tbt.models.feature_builder import FeatureBuilder
from tbt.models.metrics import evaluate_probabilities
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.training import _split_by_date


MIN_LOG_LOSS_IMPROVEMENT = 0.0001
MIN_BRIER_IMPROVEMENT = 0.00005
MIN_AUC_DELTA = -0.001
MIN_ACCURACY_DELTA = -0.002
MAX_ECE_WORSENING = 0.003


def _delta(
    challenger: dict,
    champion: dict,
) -> dict[str, float]:
    return {
        "accuracy": (
            float(challenger["accuracy"])
            - float(champion["accuracy"])
        ),
        "roc_auc": (
            float(challenger["roc_auc"])
            - float(champion["roc_auc"])
        ),
        "log_loss": (
            float(challenger["log_loss"])
            - float(champion["log_loss"])
        ),
        "brier_score": (
            float(challenger["brier_score"])
            - float(champion["brier_score"])
        ),
        "ece_10": (
            float(challenger["ece_10"])
            - float(champion["ece_10"])
        ),
    }


def _decision(
    delta: dict[str, float],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if delta["log_loss"] > -MIN_LOG_LOSS_IMPROVEMENT:
        reasons.append(
            "log_loss_not_improved_enough"
        )

    if delta["brier_score"] > -MIN_BRIER_IMPROVEMENT:
        reasons.append(
            "brier_not_improved_enough"
        )

    if delta["roc_auc"] < MIN_AUC_DELTA:
        reasons.append(
            "roc_auc_regression"
        )

    if delta["accuracy"] < MIN_ACCURACY_DELTA:
        reasons.append(
            "accuracy_regression"
        )

    if delta["ece_10"] > MAX_ECE_WORSENING:
        reasons.append(
            "calibration_regression"
        )

    return (
        len(reasons) == 0,
        reasons,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a trained challenger directly with "
            "the current champion on the same chronological holdout."
        )
    )

    parser.add_argument(
        "--challenger",
        default="api/artifacts/model.joblib",
    )

    parser.add_argument(
        "--champion",
        default="api/artifacts/champion.joblib",
    )

    parser.add_argument(
        "--report",
        default=str(
            ROOT
            / "reports"
            / "challenger_vs_champion.json"
        ),
    )

    args = parser.parse_args()

    repo = SupabaseRepository()

    challenger = load_model(
        args.challenger
    )

    champion = load_model(
        args.champion
    )

    champion_row = (
        repo.champion_model_version()
    )

    if not champion_row:
        raise SystemExit(
            "No champion model registered in Supabase"
        )

    expected_champion = str(
        champion_row.get(
            "model_version"
        )
        or ""
    )

    if champion.version != expected_champion:
        raise SystemExit(
            "Downloaded champion artifact does not match "
            f"Supabase champion: artifact={champion.version} "
            f"database={expected_champion}"
        )

    if challenger.version == champion.version:
        raise SystemExit(
            "Challenger and champion versions are identical"
        )

    challenger_row = (
        repo.latest_challenger_model_version()
    )

    if (
        not challenger_row
        or str(
            challenger_row.get(
                "model_version"
            )
            or ""
        )
        != challenger.version
    ):
        raise SystemExit(
            "Latest challenger row does not match "
            "the challenger artifact"
        )

    matches = (
        repo.get_completed_matches()
    )

    frame = (
        FeatureBuilder()
        .build_training_frame(
            matches
        )
    )

    frame = (
        frame.sort_values(
            [
                "scheduled_at",
                "match_id",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    _, _, holdout = (
        _split_by_date(
            frame,
            0.70,
            0.15,
        )
    )

    if len(holdout) < 300:
        raise SystemExit(
            "Common holdout is too small"
        )

    challenger_probability = (
        challenger.predict_proba(
            holdout
        )
    )

    champion_probability = (
        champion.predict_proba(
            holdout
        )
    )

    challenger_metrics = (
        evaluate_probabilities(
            holdout["target"],
            challenger_probability,
        )
    )

    champion_metrics = (
        evaluate_probabilities(
            holdout["target"],
            champion_probability,
        )
    )

    delta = _delta(
        challenger_metrics,
        champion_metrics,
    )

    eligible, reasons = (
        _decision(delta)
    )

    period = {
        "start": (
            pd.to_datetime(
                holdout["scheduled_at"],
                utc=True,
            )
            .min()
            .isoformat()
        ),
        "end": (
            pd.to_datetime(
                holdout["scheduled_at"],
                utc=True,
            )
            .max()
            .isoformat()
        ),
    }

    report = {
        "comparison": (
            "direct challenger vs champion "
            "on identical out-of-time holdout"
        ),
        "challenger_version": (
            challenger.version
        ),
        "champion_version": (
            champion.version
        ),
        "holdout_rows": int(
            len(holdout)
        ),
        "holdout_period": period,
        "challenger": (
            challenger_metrics
        ),
        "champion": (
            champion_metrics
        ),
        "delta_challenger_minus_champion": (
            delta
        ),
        "eligible_for_promotion": (
            eligible
        ),
        "reasons": reasons,
    }

    if eligible:
        promotion_reason = (
            "Direct OOS challenger-vs-champion comparison passed. "
            f"log_loss_delta={delta['log_loss']:.6f}; "
            f"brier_delta={delta['brier_score']:.6f}; "
            f"auc_delta={delta['roc_auc']:.6f}; "
            f"accuracy_delta={delta['accuracy']:.6f}; "
            f"ece_delta={delta['ece_10']:.6f}"
        )

        promotion = repo.promote_model(
            challenger.version,
            promotion_reason,
        )

        report[
            "lifecycle_action"
        ] = "promoted"

        report[
            "promotion_result"
        ] = promotion

    else:
        rejection_reason = (
            "Direct OOS challenger-vs-champion comparison failed: "
            + ", ".join(reasons)
        )

        repo.reject_model(
            challenger.version,
            rejection_reason,
        )

        report[
            "lifecycle_action"
        ] = "rejected"

    report_path = Path(
        args.report
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
