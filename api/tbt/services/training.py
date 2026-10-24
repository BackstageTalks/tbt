from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable

import numpy as np
import pandas as pd

from ..data.atp_leaderboards import (
    ATP_LEADERBOARD_FEATURE_NAMES,
    coverage_summary as atp_coverage_summary,
)
from ..data.atp_rank_history import (
    ATP_RANK_HISTORY_FEATURE_NAMES,
    coverage_summary as atp_rank_history_coverage_summary,
)
from ..data.wta_rank_history import (
    WTA_RANK_HISTORY_FEATURE_NAMES,
    coverage_summary as wta_rank_history_coverage_summary,
)
from ..data.wta_season_stats import (
    WTA_SEASON_FEATURE_NAMES,
    coverage_summary as wta_coverage_summary,
)
from ..models.ensemble import TennisEnsemble
from ..models.feature_builder import FEATURE_NAMES, EVIDENCE_FEATURE_NAMES, RICH_CHARTING_FEATURE_NAMES, FeatureBuilder
from ..models.momentum import MOMENTUM_FEATURE_NAMES
from ..models.metrics import evaluate_probabilities
from ..schemas import MatchRecord
from .data_quality import audit_history
from .prediction_quality import subgroup_report, history_band


PRODUCTION_FEATURE_NAMES = [
    name
    for name in FEATURE_NAMES
    if (
        name not in set(EVIDENCE_FEATURE_NAMES)
        and name not in set(MOMENTUM_FEATURE_NAMES)
        and name not in set(RICH_CHARTING_FEATURE_NAMES)
        and name != "atp_surface_opponent_form_diff"
        and name not in set(ATP_LEADERBOARD_FEATURE_NAMES)
        and name not in set(ATP_RANK_HISTORY_FEATURE_NAMES)
        and name not in set(WTA_RANK_HISTORY_FEATURE_NAMES)
        and name not in set(WTA_SEASON_FEATURE_NAMES)
    )
]

ATP_CANDIDATE_FEATURE_NAMES = (
    list(PRODUCTION_FEATURE_NAMES)
    + list(ATP_LEADERBOARD_FEATURE_NAMES)
)

WTA_CANDIDATE_FEATURE_NAMES = (
    list(PRODUCTION_FEATURE_NAMES)
    + list(WTA_SEASON_FEATURE_NAMES)
)


def _training_progress(phase: str, rows: int) -> None:
    """Stream low-cardinality fit progress and peak RSS to private Actions logs."""
    from time import monotonic
    if not hasattr(_training_progress, "_started"):
        _training_progress._started = monotonic()
    peak_mb = None
    try:
        import resource
        # GitHub training runners are Linux; ru_maxrss is KiB.
        peak_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except (ImportError, OSError):
        pass
    print(json.dumps({
        "calibration_phase": phase, "rows": rows,
        "elapsed_s": round(monotonic() - _training_progress._started, 1),
        "peak_rss_mb": peak_mb,
    }), flush=True)


def _candidate_feature_names(
    *,
    atp_leaderboards=None,
    atp_rank_history=None,
    wta_rank_history=None,
    wta_season_stats=None,
    atp_surface_opponent_form=False,
    evidence_depth=False,
    momentum=False,
):
    names = list(PRODUCTION_FEATURE_NAMES)
    if evidence_depth:
        names += EVIDENCE_FEATURE_NAMES
    if momentum:
        names += MOMENTUM_FEATURE_NAMES
    if atp_surface_opponent_form:
        names.append("atp_surface_opponent_form_diff")
    if atp_leaderboards is not None:
        names += list(ATP_LEADERBOARD_FEATURE_NAMES)
    if atp_rank_history is not None:
        names += list(ATP_RANK_HISTORY_FEATURE_NAMES)
    if wta_rank_history is not None:
        names += list(WTA_RANK_HISTORY_FEATURE_NAMES)
    if wta_season_stats is not None:
        names += list(WTA_SEASON_FEATURE_NAMES)
    return names


def _new_production_ensemble(feature_names=None, objective="accuracy") -> TennisEnsemble:
    """Governed candidate model with only explicitly enabled feature groups."""
    model = TennisEnsemble()
    model.objective = objective
    # Assign after construction so test doubles and legacy constructors that
    # accept no feature_names argument remain compatible.
    model.feature_names = list(
        PRODUCTION_FEATURE_NAMES
        if feature_names is None
        else feature_names
    )
    return model



@dataclass
class TrainingResult:
    model: TennisEnsemble
    report: dict
    feature_frame: pd.DataFrame


def _candidate_learning_window(frame, training_profile):
    """Keep historical replay context, but fit 7.2.1 only on 2024+ labels."""
    if training_profile != "top-7.2.1":
        return frame
    timestamps = pd.to_datetime(frame["scheduled_at"], utc=True)
    recent = frame.loc[timestamps >= pd.Timestamp("2024-01-01", tz="UTC")].copy()
    if recent.empty:
        raise ValueError("No 2024+ matches available for candidate training")
    return recent.reset_index(drop=True)


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


def _split_serving_refit_by_date(
    frame: pd.DataFrame,
    calibration_fraction: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use every consumed outcome while keeping serving calibration out of base fit."""
    if frame.empty:
        raise ValueError("No serving-refit rows")
    if not 0.05 <= calibration_fraction <= 0.30:
        raise ValueError("Invalid serving calibration fraction")

    ordered = frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    row_days = pd.to_datetime(ordered["scheduled_at"], utc=True).dt.date
    days = sorted(row_days.unique())
    if len(days) < 30:
        raise ValueError("Serving refit requires at least 30 distinct dates")

    split_idx = max(1, int(len(days) * (1.0 - calibration_fraction)))
    split_idx = min(split_idx, len(days) - 1)
    train_end = days[split_idx - 1]
    serving_train = ordered.loc[row_days <= train_end].copy()
    serving_calibration = ordered.loc[row_days > train_end].copy()

    if len(serving_train) < 300 or len(serving_calibration) < 120:
        raise ValueError("Serving refit partitions are too small")
    if (
        pd.to_datetime(serving_train["scheduled_at"], utc=True).max().normalize()
        >= pd.to_datetime(serving_calibration["scheduled_at"], utc=True).min().normalize()
    ):
        raise RuntimeError("Serving refit date overlap")
    return serving_train, serving_calibration


def refit_serving_model(result: TrainingResult) -> TennisEnsemble:
    """Refit only after promotion approval, consuming the already-used holdout."""
    selected = result.model
    serving_train, serving_calibration = _split_serving_refit_by_date(result.feature_frame)

    serving = _new_production_ensemble()
    serving.feature_names = list(
        getattr(selected, "feature_names", None)
        or PRODUCTION_FEATURE_NAMES
    )
    serving.fit_frozen(
        serving_train,
        serving_calibration,
        blend_weight=float(selected.blend_weight),
        elo_weight=float(getattr(selected, "elo_weight", 0.0)),
        calibrator_kind=str(selected.calibrator.kind),
        tour_calibrator_kinds={
            tour: cal.kind for tour, cal in
            (getattr(selected, "tour_calibrators", {}) or {}).items()
        },
        atp_blend_weight=getattr(selected, "atp_blend_weight", None),
        atp_elo_weight=getattr(selected, "atp_elo_weight", None),
    )

    selected_metadata = dict(getattr(selected, "metadata", {}) or {})
    full_period = _period(result.feature_frame)
    serving.metadata = {
        **serving.metadata,
        "model_version": serving.version,
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "serving_refit": True,
        "selection_model_version": selected.version,
        "selection_holdout_fingerprint": selected_metadata.get("holdout_fingerprint"),
        "selection_history_end": selected_metadata.get("history_end"),
        "selection_evaluation_end": selected_metadata.get("evaluation_end"),
        "history_start": full_period["start"],
        "history_end": full_period["end"],
        "evaluation_end": full_period["end"],
        "training_matches": int(len(result.feature_frame)),
        "production_train_matches": int(len(serving_train)),
        "production_calibration_matches": int(len(serving_calibration)),
        "rank_provenance": selected_metadata.get("rank_provenance"),
        "independent_serve_return": bool(selected_metadata.get("independent_serve_return", False)),
        "independent_direct_rates": bool(selected_metadata.get("independent_direct_rates", False)),
        "point_weighted_quality": bool(selected_metadata.get("point_weighted_quality", False)),
        "holdout_metrics": selected_metadata.get("holdout_metrics"),
        "elo_baseline_metrics": selected_metadata.get("elo_baseline_metrics"),
        "holdout_delta_vs_elo": selected_metadata.get("holdout_delta_vs_elo"),
        "evaluation_method": selected_metadata.get("evaluation_method"),
        "static_environment_features_enabled": selected_metadata.get(
            "static_environment_features_enabled", True
        ),
        "static_environment_features": selected_metadata.get(
            "static_environment_features", []
        ),
        "historical_weather_training_enabled": False,
        "historical_weather_reason": selected_metadata.get(
            "historical_weather_reason",
            "waiting_for_point_in_time_pre_match_forecast_snapshots",
        ),
    }
    return serving


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
) -> dict[str, str | None]:
    if frame.empty:
        return {
            "start": None,
            "end": None,
        }

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


def _eligible_evaluation(test, production_model=None, promotion_history=(), *, as_of=None):
    """Only completed whole UTC days unseen by the champion and decisions."""
    today_utc = pd.Timestamp(as_of if as_of is not None else pd.Timestamp.now(tz="UTC"))
    if today_utc.tzinfo is None:
        raise ValueError("Holdout evaluation cutoff must be timezone-aware")
    today_utc = today_utc.tz_convert("UTC").normalize()
    cutoffs = []
    if production_model is not None:
        metadata = getattr(production_model, "metadata", {}) or {}
        cutoff = _parse_provenance_datetime(metadata.get("history_end"))
        if cutoff is None:
            return test.iloc[:0].copy(), "production_history_cutoff_unknown"
        cutoffs.append(pd.Timestamp(cutoff).normalize())
    for decision in promotion_history:
        # A dry-run with promote=false must not consume unseen evaluation data.
        if (isinstance(decision, dict)
                and decision.get("promotion_requested") is False
                and decision.get("decision") == "not_requested"):
            continue
        period = decision.get("holdout_period") if isinstance(decision, dict) else None
        cutoff = _parse_provenance_datetime((period or {}).get("end"))
        if cutoff is None:
            return test.iloc[:0].copy(), "previous_decision_cutoff_unknown"
        cutoffs.append(pd.Timestamp(cutoff).normalize())
    days = pd.to_datetime(test.scheduled_at, utc=True).dt.normalize()
    eligible = days < today_utc
    if cutoffs:
        eligible &= days > max(cutoffs)
    test = test.loc[eligible].copy()
    # Fail closed until at least three distinct, fully completed UTC dates exist.
    eligible_days = pd.to_datetime(test.scheduled_at, utc=True).dt.normalize().nunique()
    if eligible_days < 3:
        return test.iloc[:0].copy(), "no_eligible_unseen_evaluation_rows"
    return test, None


def _augment_feature_columns(
    frame: pd.DataFrame,
    matches: Iterable[MatchRecord],
    provider,
    feature_names,
    coverage_fields: dict[str, str],
    *,
    extractor,
    inplace: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Bound rank/season feature memory without discarding any match.

    Previously one Python dict per row was retained for each auxiliary feature
    family (up to ~1m dictionaries), while copying the entire training frame
    four more times. Store numeric values in a compact ndarray instead. The
    default remains non-mutating for direct callers; the training pipeline
    exclusively owns its frame and can opt into in-place augmentation.
    """
    augmented = frame if inplace else frame.copy()
    names = list(feature_names)
    values = np.zeros((len(frame), len(names)), dtype=np.float64)
    if provider is not None:
        source = {match.match_id: match for match in matches}
        for index, match_id in enumerate(frame["match_id"]):
            oriented, _ = FeatureBuilder.orient_for_training(source[match_id])
            row = extractor(provider, oriented)
            for j, name in enumerate(names):
                values[index, j] = float(row.get(name, 0.0))
    for j, name in enumerate(names):
        augmented[name] = values[:, j]
    columns = {name: j for j, name in enumerate(names)}
    coverage = {"rows": len(frame)}
    for metric, name in coverage_fields.items():
        coverage[metric] = (
            float(values[:, columns[name]].sum()) / len(frame)
            if len(frame) else 0.0
        )
    return augmented, coverage


def _augment_atp_leaderboard_features(
    frame: pd.DataFrame,
    matches: Iterable[MatchRecord],
    atp_leaderboards,
    *,
    inplace: bool = False,
) -> tuple[pd.DataFrame, dict]:
    return _augment_feature_columns(
        frame, matches, atp_leaderboards, ATP_LEADERBOARD_FEATURE_NAMES,
        {"known_both_rate": "atp_leaderboard_known_both",
         "surface_known_both_rate": "atp_surface_leaderboard_known_both"},
        extractor=lambda provider, oriented: provider.features_for_match(oriented, current=False),
        inplace=inplace,
    )


def _augment_atp_rank_history_features(
    frame: pd.DataFrame,
    matches: Iterable[MatchRecord],
    atp_rank_history,
    *,
    inplace: bool = False,
) -> tuple[pd.DataFrame, dict]:
    return _augment_feature_columns(
        frame, matches, atp_rank_history, ATP_RANK_HISTORY_FEATURE_NAMES,
        {"known_both_rate": "atp_hist_known_both",
         "momentum_4w_known_both_rate": "atp_hist_momentum_4w_known_both",
         "momentum_12w_known_both_rate": "atp_hist_momentum_12w_known_both"},
        extractor=lambda provider, oriented: provider.features_for_match(oriented),
        inplace=inplace,
    )


def _augment_wta_rank_history_features(
    frame: pd.DataFrame,
    matches: Iterable[MatchRecord],
    wta_rank_history,
    *,
    inplace: bool = False,
) -> tuple[pd.DataFrame, dict]:
    return _augment_feature_columns(
        frame, matches, wta_rank_history, WTA_RANK_HISTORY_FEATURE_NAMES,
        {"known_both_rate": "wta_hist_known_both",
         "momentum_4w_known_both_rate": "wta_hist_momentum_4w_known_both",
         "momentum_12w_known_both_rate": "wta_hist_momentum_12w_known_both"},
        extractor=lambda provider, oriented: provider.features_for_match(oriented),
        inplace=inplace,
    )


def _augment_wta_season_features(
    frame: pd.DataFrame,
    matches: Iterable[MatchRecord],
    wta_season_stats,
    *,
    inplace: bool = False,
) -> tuple[pd.DataFrame, dict]:
    return _augment_feature_columns(
        frame, matches, wta_season_stats, WTA_SEASON_FEATURE_NAMES,
        {"known_both_rate": "wta_season_stats_known_both"},
        extractor=lambda provider, oriented: provider.features_for_match(oriented, current=False),
        inplace=inplace,
    )


def paired_wta_holdout_diagnostics(test, candidate_p, champion_p):
    """Descriptive only: untouched WTA holdout, never used for model selection.

    Distinguish missing features from zero-valued feature differences. A zero
    break-point difference is not proof that both break-point priors exist.
    """
    if champion_p is None or "tour_atp" not in test:
        return {"status": "NO_COMPARABLE_CHAMPION"}
    candidate_p = np.asarray(candidate_p, dtype=float)
    champion_p = np.asarray(champion_p, dtype=float)
    if len(test) != len(candidate_p) or len(test) != len(champion_p):
        raise ValueError("Paired WTA probabilities must share exact holdout rows")
    wta = np.isclose(test["tour_atp"].to_numpy(dtype=float), 0.)
    if not wta.any():
        return {"status": "NO_WTA_HOLDOUT", "n": 0}
    target = test["target"].to_numpy(dtype=int)
    metrics = ("accuracy", "log_loss", "brier_score", "ece_10")
    def scored(mask):
        n = int(mask.sum())
        if n < 30:
            return {"n": n, "status": "INSUFFICIENT_SUBGROUP"}
        left = evaluate_probabilities(target[mask], candidate_p[mask])
        right = evaluate_probabilities(target[mask], champion_p[mask])
        return {"n": n, "status": "DESCRIPTIVE_HOLDOUT_ONLY",
                "candidate": {k: left.get(k) for k in metrics},
                "champion": {k: right.get(k) for k in metrics},
                "delta": {k: _metric_delta(left, right, k) for k in metrics}}
    fields = (
        "stats_known_both", "surface_stats_known_both",
        "wta_hist_known_both", "wta_season_stats_known_both",
    )
    cohorts = {}
    for field in fields:
        if field not in test:
            cohorts[field] = {"status": "FEATURE_NOT_AVAILABLE"}
            continue
        valid = pd.to_numeric(test[field], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(valid[wta]).all():
            raise ValueError("Nonfinite WTA feature availability in audited holdout")
        cohorts[field] = {
            "known": scored(wta & (valid >= .5)),
            "missing": scored(wta & (valid < .5)),
        }
    # Break point values describe nonzero differential signal, not coverage.
    bp = {}
    for field in ("break_point_serve_diff", "break_point_return_diff"):
        if field in test:
            values = pd.to_numeric(test[field], errors="coerce").to_numpy(dtype=float)
            bp[field] = {
                "nonzero_signal_rows": int((wta & np.isfinite(values) & (np.abs(values) > 1e-12)).sum()),
                "status": "NONZERO_SIGNAL_NOT_COVERAGE",
            }
    return {"status": "DESCRIPTIVE_HOLDOUT_ONLY", "n": int(wta.sum()),
            "full_wta": scored(wta), "availability_cohorts": cohorts,
            "break_point_signal": bp,
            "never_select_model_on_this_holdout": True}


def train_from_matches(
    matches: Iterable[
        MatchRecord
    ],
    min_matches: int = 2500,
    *,
    production_model=None,
    promotion_history=(),
    atp_leaderboards=None,
    atp_rank_history=None,
    wta_rank_history=None,
    wta_season_stats=None,
    training_profile="standard",
    verified_frame: pd.DataFrame | None = None,
) -> TrainingResult:
    if training_profile not in {"standard", "top-7.2.1"}:
        raise ValueError("Unknown training profile")
    # Do not allow future rows to become eligible while the lengthy protected
    # feature replay is running; use exactly the audit cutoff sealed at freeze.
    frozen_audit_at = (verified_frame.attrs.get("history_audit_at")
                       if verified_frame is not None else None)
    if frozen_audit_at is not None:
        from datetime import datetime
        cutoff = datetime.fromisoformat(frozen_audit_at)
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("Naive frozen history audit timestamp")
    else:
        cutoff = None
    matches, quality = audit_history(matches, now=cutoff)
    matches, rank_provenance = _enforce_rank_provenance(matches)
    _training_progress("validated_history", len(matches))
    # 7.2.1 uses independent serve and return availability. The champion
    # retains the original joint semantics via artifact metadata in serving.
    builder = FeatureBuilder(
        independent_serve_return=(training_profile == "top-7.2.1"),
        independent_direct_rates=(training_profile == "top-7.2.1"),
        point_weighted_quality=(training_profile == "top-7.2.1"),
    )

    if verified_frame is None:
        frame = builder.build_training_frame(matches)
    else:
        # The protected runner has verified this cache against the exact run,
        # profile, immutable full-input backup and complete match identities.
        frame = verified_frame  # already owned and SHA-read-back verified; avoid ~1m-row duplicate
        if (len(frame) != len(matches)
                or not frame["match_id"].is_unique
                or set(frame["match_id"].astype(str)) !=
                    {str(m.match_id) for m in matches}):
            raise ValueError("Verified point-in-time frame/source mismatch")
    _training_progress("point_in_time_feature_replay", len(frame))
    frame, atp_leaderboard_coverage = _augment_atp_leaderboard_features(
        frame, matches, atp_leaderboards, inplace=True
    )
    frame, atp_rank_history_coverage = _augment_atp_rank_history_features(
        frame, matches, atp_rank_history, inplace=True
    )
    frame, wta_rank_history_coverage = _augment_wta_rank_history_features(
        frame, matches, wta_rank_history, inplace=True
    )
    frame, wta_season_coverage = _augment_wta_season_features(
        frame, matches, wta_season_stats, inplace=True
    )

    _training_progress("auxiliary_features_complete", len(frame))
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
    replay_rows = len(frame)
    frame = _candidate_learning_window(frame, training_profile)

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

    diagnostics = None
    objective = "log_loss" if training_profile == "top-7.2.1" else "accuracy"
    if training_profile == "top-7.2.1":
        from .training_inputs import input_diagnostics, require_informative_inputs
        names = _candidate_feature_names(
            atp_leaderboards=atp_leaderboards, atp_rank_history=atp_rank_history,
            wta_rank_history=wta_rank_history, wta_season_stats=wta_season_stats,
            atp_surface_opponent_form=True, evidence_depth=True, momentum=True,
        )
        diagnostics = input_diagnostics({"train": train, "calibration": calibration}, names)
        require_informative_inputs(diagnostics)

    _training_progress("fit_estimators_start", len(train))
    evaluation_model = (
        (
            _new_production_ensemble(
                _candidate_feature_names(
                    atp_leaderboards=atp_leaderboards,
                    atp_rank_history=atp_rank_history,
                    wta_rank_history=wta_rank_history,
                    wta_season_stats=wta_season_stats,
                    atp_surface_opponent_form=(training_profile == "top-7.2.1"),
                    evidence_depth=(training_profile == "top-7.2.1"),
                    momentum=(training_profile == "top-7.2.1"),
                ), objective=objective,
            )
            if (
                atp_leaderboards is not None
                or atp_rank_history is not None
                or wta_rank_history is not None
                or wta_season_stats is not None
                or training_profile == 'top-7.2.1'
            )
            else _new_production_ensemble(objective=objective)
        )
    )
    # Enabled only for new 7.2.1 research; standard and legacy fits are unchanged.
    evaluation_model.atp_blend_specialization = training_profile == "top-7.2.1"
    evaluation_model.fit(train, calibration)

    _training_progress("fit_estimators_complete", len(train))
    if training_profile == "top-7.2.1":
        evaluation_model.version = "v7.2.1-" + evaluation_model.version

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

    production_probabilities = (
        production_model.predict_proba(test)
        if production_model is not None and len(test) else None
    )
    production_metrics = (
        evaluate_probabilities(test["target"], production_probabilities)
        if production_probabilities is not None else {}
    )
    production_subgroups = (
        subgroup_report(test, production_probabilities)
        if production_probabilities is not None else {}
    )
    delta_vs_production = {
        key: _metric_delta(holdout_metrics, production_metrics, key)
        for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
    }
    report = {
        "training_profile": training_profile,
        "learning_window": {
            "start_inclusive_utc": "2024-01-01T00:00:00Z" if training_profile == "top-7.2.1" else None,
            "historical_replay_rows": replay_rows,
            "eligible_learning_rows": len(frame),
            "context_only_rows": replay_rows - len(frame),
            "split_policy": "70/15/15 chronological whole UTC days within learning window",
        },
        "optimization_objective": objective,
        "input_diagnostics": diagnostics,
        "top_market_validation": {
            "status": "NOT_EVALUATED",
            "required": "Independent pre-match odds >=1.50, at most 10 picks/day, no forced fill",
            "promotion_ready_for_top": False,
        },
        "production_holdout": production_metrics,
        "production_subgroups": production_subgroups,
        "delta_vs_production": delta_vs_production,
        "wta_regression_diagnostics": paired_wta_holdout_diagnostics(
            test, test_p, production_probabilities),
        "data_quality": quality,
        "rank_provenance": rank_provenance,
        "atp_leaderboards": {
            **atp_leaderboard_coverage,
            "features": list(ATP_LEADERBOARD_FEATURE_NAMES),
            "historical_policy": "previous_completed_season_only",
            "candidate_features_enabled": bool(atp_leaderboards is not None),
            "promotion_required_for_serving": True,
        },
        "atp_rank_history": {
            **atp_rank_history_coverage,
            "features": list(ATP_RANK_HISTORY_FEATURE_NAMES),
            "historical_policy": "latest_weekly_snapshot_strictly_before_match_date",
            "candidate_features_enabled": bool(atp_rank_history is not None),
            "promotion_required_for_serving": True,
        },
        "wta_rank_history": {
            **wta_rank_history_coverage,
            "features": list(WTA_RANK_HISTORY_FEATURE_NAMES),
            "historical_policy": "latest_weekly_snapshot_strictly_before_match_date",
            "candidate_features_enabled": bool(wta_rank_history is not None),
            "promotion_required_for_serving": True,
        },
        "wta_season_stats": {
            **wta_season_coverage,
            "features": list(WTA_SEASON_FEATURE_NAMES),
            "historical_policy": "previous_completed_season_only",
            "current_policy": "previous_completed_season_only",
            "candidate_features_enabled": bool(wta_season_stats is not None),
            "promotion_required_for_serving": True,
        },
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
            "tour_blend_experiment": (
                (evaluation_model.metadata or {}).get("tour_blend_experiment")
            ),
            "blend_weight_boost": (
                evaluation_model
                .blend_weight
            ),
            "calibration_method": (
                evaluation_model
                .calibrator
                .kind
            ),
            "tour_calibration_methods": dict(
                (evaluation_model.metadata or {}).get("tour_calibration_methods") or {}
            ),
            "tour_calibration_validation": dict(
                (evaluation_model.metadata or {}).get("tour_calibration_validation") or {}
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
        "independent_serve_return": training_profile == "top-7.2.1",
        "independent_direct_rates": training_profile == "top-7.2.1",
        "point_weighted_quality": training_profile == "top-7.2.1",
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
        "static_environment_features_enabled": True,
        "static_environment_features": [
            "travel_km_advantage", "travel_known",
            "altitude_change_advantage", "altitude_change_known",
            "altitude_serve_interaction", "indoor",
        ],
        "historical_weather_training_enabled": False,
        "historical_weather_reason": "waiting_for_point_in_time_pre_match_forecast_snapshots",
        **production_model.metadata,
    }

    return TrainingResult(
        production_model,
        report,
        frame,
    )
