from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable

import pandas as pd

from ..models.ensemble import TennisEnsemble
from ..models.feature_builder import FeatureBuilder
from ..models.metrics import evaluate_probabilities
from ..schemas import MatchRecord
from .data_quality import audit_history
from .prediction_quality import subgroup_report, history_band


@dataclass
class TrainingResult:
    model: TennisEnsemble
    report: dict
    feature_frame: pd.DataFrame


def _split_by_date(
    frame: pd.DataFrame,
    train_fraction: float,
    calibration_fraction: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """
    Split chronologically by whole UTC calendar days.

    No calendar day can appear in more than one partition.
    """

    if frame.empty:
        raise ValueError(
            "No training rows"
        )

    if (
        train_fraction <= 0.0
        or calibration_fraction <= 0.0
        or (
            train_fraction
            + calibration_fraction
        )
        >= 1.0
    ):
        raise ValueError(
            "Invalid train/calibration fractions"
        )

    ordered = (
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

    timestamps = pd.to_datetime(
        ordered["scheduled_at"],
        utc=True,
    )

    row_days = timestamps.dt.date

    days = sorted(
        row_days.unique()
    )

    if len(days) < 30:
        raise ValueError(
            "Training history must span "
            "at least 30 distinct dates"
        )

    train_day_idx = max(
        1,
        int(
            len(days)
            * train_fraction
        ),
    )

    cal_day_idx = max(
        train_day_idx + 1,
        int(
            len(days)
            * (
                train_fraction
                + calibration_fraction
            )
        ),
    )

    cal_day_idx = min(
        cal_day_idx,
        len(days) - 1,
    )

    train_end = days[
        train_day_idx - 1
    ]

    calibration_end = days[
        cal_day_idx - 1
    ]

    train = (
        ordered[
            row_days
            <= train_end
        ]
        .copy()
    )

    calibration = (
        ordered[
            (
                row_days
                > train_end
            )
            & (
                row_days
                <= calibration_end
            )
        ]
        .copy()
    )

    test = (
        ordered[
            row_days
            > calibration_end
        ]
        .copy()
    )

    if train.empty:
        raise ValueError(
            "Training partition is empty"
        )

    if calibration.empty:
        raise ValueError(
            "Calibration partition is empty"
        )

    if test.empty:
        raise ValueError(
            "Holdout partition is empty"
        )

    train_last_day = (
        pd.to_datetime(
            train["scheduled_at"],
            utc=True,
        )
        .max()
        .normalize()
    )

    calibration_first_day = (
        pd.to_datetime(
            calibration["scheduled_at"],
            utc=True,
        )
        .min()
        .normalize()
    )

    calibration_last_day = (
        pd.to_datetime(
            calibration["scheduled_at"],
            utc=True,
        )
        .max()
        .normalize()
    )

    test_first_day = (
        pd.to_datetime(
            test["scheduled_at"],
            utc=True,
        )
        .min()
        .normalize()
    )

    if (
        train_last_day
        >= calibration_first_day
    ):
        raise RuntimeError(
            "Training/calibration date overlap"
        )

    if (
        calibration_last_day
        >= test_first_day
    ):
        raise RuntimeError(
            "Calibration/holdout date overlap"
        )

    return (
        train,
        calibration,
        test,
    )


def _group_metrics(
    frame: pd.DataFrame,
    probabilities,
) -> dict:
    result: dict = {}

    scored = frame.copy()

    scored[
        "probability"
    ] = probabilities

    for column in (
        "tour",
        "surface",
    ):
        result[
            column
        ] = {}

        for (
            value,
            group,
        ) in scored.groupby(
            column
        ):
            if len(group) < 50:
                continue

            result[
                column
            ][
                str(value)
            ] = (
                evaluate_probabilities(
                    group["target"],
                    group[
                        "probability"
                    ],
                )
            )

    return result


def _metric_delta(
    model_metrics: dict,
    baseline_metrics: dict,
    key: str,
) -> float | None:
    model_value = (
        model_metrics.get(
            key
        )
    )

    baseline_value = (
        baseline_metrics.get(
            key
        )
    )

    if (
        model_value is None
        or baseline_value is None
    ):
        return None

    return (
        float(model_value)
        - float(
            baseline_value
        )
    )


def _period(
    frame: pd.DataFrame,
) -> dict[str, str]:
    timestamps = pd.to_datetime(
        frame[
            "scheduled_at"
        ],
        utc=True,
    )

    return {
        "start": (
            timestamps
            .min()
            .isoformat()
        ),
        "end": (
            timestamps
            .max()
            .isoformat()
        ),
    }



def _parse_provenance_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        result = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _verified_rank_provenance(match: MatchRecord) -> bool:
    """Historical ranks are usable only with explicit point-in-time provenance.

    Accepted provenance lives in provider_payload["_tbt_rank_provenance"] and must
    explicitly state point_in_time=True, name a source, and carry an as_of
    timestamp that is not later than the match start.
    """
    payload = (
        match.provider_payload
        if isinstance(match.provider_payload, dict)
        else {}
    )
    provenance = payload.get("_tbt_rank_provenance")
    if not isinstance(provenance, dict):
        return False
    if provenance.get("point_in_time") is not True:
        return False
    if not str(provenance.get("source") or "").strip():
        return False

    as_of = _parse_provenance_datetime(provenance.get("as_of"))
    if as_of is None:
        return False

    scheduled_at = match.scheduled_at
    if scheduled_at.tzinfo is None:
        raise ValueError("Naive historical timestamp")
    scheduled_at = scheduled_at.astimezone(timezone.utc)

    return as_of <= scheduled_at


def _enforce_rank_provenance(
    matches: Iterable[MatchRecord],
) -> tuple[list[MatchRecord], dict]:
    """Strip unverified historical rankings before feature construction."""
    cleaned: list[MatchRecord] = []
    rows_with_rank_values = 0
    verified_rows = 0
    stripped_rows = 0
    stripped_values = 0
    retained_values = 0

    for match in matches:
        rank_values = (
            match.player1_rank,
            match.player2_rank,
        )
        present = sum(value is not None for value in rank_values)
        if present:
            rows_with_rank_values += 1

        if present and _verified_rank_provenance(match):
            verified_rows += 1
            retained_values += present
            cleaned.append(match)
            continue

        if present:
            stripped_rows += 1
            stripped_values += present
            cleaned.append(
                replace(
                    match,
                    player1_rank=None,
                    player2_rank=None,
                )
            )
        else:
            cleaned.append(match)

    return cleaned, {
        "policy": "historical_rank_requires_explicit_point_in_time_provenance",
        "rows_with_rank_values": rows_with_rank_values,
        "verified_rows": verified_rows,
        "stripped_rows": stripped_rows,
        "stripped_values": stripped_values,
        "retained_values": retained_values,
    }


def _holdout_fingerprint(frame: pd.DataFrame) -> str:
    """Stable identity for the exact untouched holdout used for a decision."""
    ordered = frame.sort_values(
        ["scheduled_at", "match_id"]
    )
    payload = [
        {
            "match_id": str(row.match_id),
            "scheduled_at": pd.Timestamp(row.scheduled_at).tz_convert("UTC").isoformat(),
        }
        for row in ordered.itertuples(index=False)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _eligible_evaluation(test, production_model=None, promotion_history=()):
    """Only later whole days unseen by the champion and previous decisions."""
    cutoffs = []
    if production_model is not None:
        metadata = getattr(production_model, "metadata", {}) or {}
        cutoff = _parse_provenance_datetime(metadata.get("history_end"))
        if cutoff is None:
            return test.iloc[:0].copy(), "production_history_cutoff_unknown"
        cutoffs.append(pd.Timestamp(cutoff).normalize())
    for decision in promotion_history:
        period = decision.get("holdout_period") if isinstance(decision, dict) else None
        cutoff = _parse_provenance_datetime((period or {}).get("end"))
        if cutoff is None:
            return test.iloc[:0].copy(), "previous_decision_cutoff_unknown"
        cutoffs.append(pd.Timestamp(cutoff).normalize())
    if cutoffs:
        days = pd.to_datetime(test.scheduled_at, utc=True).dt.normalize()
        test = test.loc[days > max(cutoffs)].copy()
    return test, None if len(test) else "no_eligible_unseen_evaluation_rows"


def train_from_matches(
    matches: Iterable[
        MatchRecord
    ],
    min_matches: int = 2500,
    *,
    production_model=None,
    promotion_history=(),
) -> TrainingResult:
    matches, quality = audit_history(matches)
    matches, rank_provenance = _enforce_rank_provenance(matches)
    builder = FeatureBuilder()

    frame = (
        builder
        .build_training_frame(
            matches
        )
    )

    if (
        len(frame)
        < min_matches
    ):
        raise ValueError(
            f"Only {len(frame)} completed "
            "matches available; at least "
            f"{min_matches} are required"
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

    source = {m.match_id: m for m in matches}
    frame['competition'] = frame.match_id.map(lambda key: source[key].tournament_level or 'unknown')
    frame['tournament'] = frame.match_id.map(lambda key: source[key].tournament or 'unknown')
    frame['history_band'] = frame.data_depth.map(lambda value: history_band(round(float(value) * 50)))
    frame['surface_history_band'] = frame.surface_history_count.map(history_band)

    # -------------------------------------------------
    # Strict out-of-time evaluation
    # 70% train / 15% calibration / 15% holdout
    # -------------------------------------------------

    (
        train,
        calibration,
        test,
    ) = _split_by_date(
        frame,
        0.70,
        0.15,
    )

    test, eligibility_reason = _eligible_evaluation(test, production_model, promotion_history)
    holdout_fingerprint = _holdout_fingerprint(test) if len(test) else ""

    evaluation_model = (
        TennisEnsemble()
        .fit(
            train,
            calibration,
        )
    )

    test_p = (
        evaluation_model
        .predict_proba(
            test
        )
    )

    elo_p = (
        test[
            "elo_probability"
        ]
        .astype(float)
        .clip(
            0.01,
            0.99,
        )
        .to_numpy()
    )

    holdout_metrics = (
        evaluate_probabilities(
            test[
                "target"
            ],
            test_p,
        )
    )

    elo_holdout_metrics = (
        evaluate_probabilities(
            test[
                "target"
            ],
            elo_p,
        )
    )

    holdout_delta = {
        "accuracy": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "accuracy",
            )
        ),
        "roc_auc": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "roc_auc",
            )
        ),
        "log_loss": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "log_loss",
            )
        ),
        "brier_score": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "brier_score",
            )
        ),
        "ece_10": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "ece_10",
            )
        ),
    }

    production_metrics = (
        evaluate_probabilities(test["target"], production_model.predict_proba(test))
        if production_model is not None and len(test) else {}
    )
    delta_vs_production = {
        key: _metric_delta(holdout_metrics, production_metrics, key)
        for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
    }
    report = {
        "production_holdout": production_metrics,
        "delta_vs_production": delta_vs_production,
        "data_quality": quality,
        "rank_provenance": rank_provenance,
        "evaluation_governance": {
            "holdout_fingerprint": holdout_fingerprint,
            "holdout_reuse_policy": (
                "A holdout fingerprint may support at most one production "
                "promotion decision. Later tuning must use later unseen/live data."
            ),
            "promotion_reference": "production_and_elo_on_same_eligible_unseen_set",
            "production_version": getattr(production_model, "version", None),
            "production_present": production_model is not None,
            "eligibility_reason": eligibility_reason,
        },
        "method": (
            "strict chronological split by "
            "whole UTC calendar days"
        ),
        "data": {
            "matches_total": int(
                len(frame)
            ),
            "train": int(
                len(train)
            ),
            "calibration": int(
                len(calibration)
            ),
            "holdout": int(
                len(test)
            ),
            "start": (
                pd.to_datetime(
                    frame[
                        "scheduled_at"
                    ],
                    utc=True,
                )
                .min()
                .isoformat()
            ),
            "end": (
                pd.to_datetime(
                    frame[
                        "scheduled_at"
                    ],
                    utc=True,
                )
                .max()
                .isoformat()
            ),
            "target_rate": float(
                frame[
                    "target"
                ].mean()
            ),
        },
        "periods": {
            "train": (
                _period(
                    train
                )
            ),
            "calibration": (
                _period(
                    calibration
                )
            ),
            "holdout": (
                _period(
                    test
                )
            ),
        },
        "holdout": (
            holdout_metrics
        ),
        "elo_baseline_holdout": (
            elo_holdout_metrics
        ),
        "delta_vs_elo": (
            holdout_delta
        ),
        "subgroups": subgroup_report(test, test_p),
        "evaluation_model": {
            "blend_weight_boost": (
                evaluation_model
                .blend_weight
            ),
            "calibration_method": (
                evaluation_model
                .calibrator
                .kind
            ),
        },
    }

    production_model = evaluation_model
    production_train, production_calibration = train, calibration

    production_model.metadata = {
        "model_version": (
            production_model.version
        ),
        "trained_at": (
            pd.Timestamp.now(
                tz="UTC"
            ).isoformat()
        ),
        "training_matches": int(
            len(frame)
        ),
        "production_train_matches": int(
            len(
                production_train
            )
        ),
        "production_calibration_matches": int(
            len(
                production_calibration
            )
        ),
        "history_start": (
            report[
                "data"
            ][
                "start"
            ]
        ),
        "history_end": _period(calibration)["end"],
        "evaluation_end": _period(test)["end"],
        "holdout_fingerprint": holdout_fingerprint,
        "rank_provenance": rank_provenance,
        "holdout_metrics": (
            holdout_metrics
        ),
        "elo_baseline_metrics": (
            elo_holdout_metrics
        ),
        "holdout_delta_vs_elo": (
            holdout_delta
        ),
        "target_rate": (
            report[
                "data"
            ][
                "target_rate"
            ]
        ),
        "evaluation_method": (
            report[
                "method"
            ]
        ),
        **production_model.metadata,
    }

    return TrainingResult(
        production_model,
        report,
        frame,
    )
