"""Private, paired PIT holdout evidence. Never uses market inputs or changes serving."""
from __future__ import annotations

from datetime import timezone
from hashlib import sha256
import json
import math

import numpy as np
import pandas as pd

from ..models.feature_builder import FeatureBuilder


FIELDS = (
    "data_depth", "surface_history_count", "stats_known_both",
    "surface_stats_known_both", "rank_known_both",
)


def _finite_probability(value):
    value = float(value)
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        raise ValueError("Nonfinite or invalid holdout probability")
    return value


def _utc(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("Naive holdout fixture timestamp")
    return timestamp.tz_convert(timezone.utc).isoformat()


def make_paired_holdout(
    frame, source, champion_probabilities, candidate_probabilities,
    *, champion_version, candidate_version, fingerprint,
    candidate_feature_names, champion_feature_names,
):
    """Preserve exact same-fixture model scores and pre-match feature evidence.

    Rows are chronological *already inspected* holdout evidence, never a new
    untouched holdout. No quote, EV, selection outcome or price is included.
    """
    if not all(isinstance(s, str) and s.strip() for s in
               (champion_version, candidate_version, fingerprint)):
        raise ValueError("Missing pinned model identity or holdout fingerprint")
    if frame.empty:
        raise ValueError("No evaluated holdout rows")
    if not frame["match_id"].is_unique:
        raise ValueError("Duplicate match identity in holdout")
    forbidden = ("odds", "bookmaker", "market_", "implied_probability", "ev_", "roi", "value_bet", "price_")
    for names in (candidate_feature_names, champion_feature_names):
        if not names or len(set(names)) != len(names) or not set(names).issubset(frame.columns):
            raise ValueError("Model feature contract differs from frozen evaluation frame")
        if any(any(fragment in str(name).lower() for fragment in forbidden) for name in names):
            raise ValueError("Sports model feature contract contains market-derived data")
    cp = np.asarray(champion_probabilities, dtype=float)
    np_ = np.asarray(candidate_probabilities, dtype=float)
    if cp.shape != (len(frame),) or np_.shape != cp.shape:
        raise ValueError("Paired score lengths differ")
    rows = []
    for idx, row in enumerate(frame.itertuples(index=False)):
        values = row._asdict()
        key = values["match_id"]
        match = source.get(key)
        if match is None or not match.is_completed:
            raise ValueError("Missing completed source match for paired evaluation")
        oriented, target = FeatureBuilder.orient_for_training(match)
        if (float(values["target"]) not in (0., 1.) or target != int(values["target"]) or
                _utc(oriented.scheduled_at) != _utc(values["scheduled_at"]) or
                str(oriented.surface) != str(values["surface"]) or
                str(oriented.tour) != str(values["tour"]) or
                str(oriented.winner_id) not in {str(oriented.player1_id), str(oriented.player2_id)}):
            raise ValueError("Label/orientation/time/identity mismatch")
        feature_evidence = {}
        for field in FIELDS:
            value = float(values[field])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid frozen feature evidence: {field}")
            if field in {"data_depth", "stats_known_both", "surface_stats_known_both", "rank_known_both"} and value > 1:
                raise ValueError(f"Out-of-range frozen evidence: {field}")
            if field in {"stats_known_both", "surface_stats_known_both", "rank_known_both"} and value not in (0., 1.):
                raise ValueError(f"Nonbinary frozen evidence: {field}")
            feature_evidence[field] = value
        feature_values = {}
        for name in sorted(set(candidate_feature_names) | set(champion_feature_names)):
            x = float(values[name])
            if not math.isfinite(x):
                raise ValueError(f"Nonfinite frozen feature: {name}")
            # Archive weather is post-match observation, explicitly masked by
            # the existing ensemble. Preserve the actual zeroed model input.
            feature_values[name] = 0. if name in {
                "weather_serve_interaction", "weather_known"} else x
        digest = sha256(json.dumps(feature_values, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        rows.append({
            "match_id": str(key),
            "scheduled_at": _utc(values["scheduled_at"]),
            "player1_id": str(oriented.player1_id),
            "player2_id": str(oriented.player2_id),
            "winner_id": str(oriented.winner_id),
            "target_player1_win": target,
            "tour": str(values["tour"]),
            "competition": str(values["competition"]),
            "tournament": str(values["tournament"]),
            "surface": str(values["surface"]),
            "feature_vector_sha256": digest,
            "pre_match_features": feature_values,
            "pre_match_feature_evidence": feature_evidence,
            "production_player1_probability": _finite_probability(cp[idx]),
            "candidate_player1_probability": _finite_probability(np_[idx]),
        })
    return {
        "schema": 1,
        "evaluation": "previously_inspected_chronological_holdout_not_prospective",
        "candidate_version": candidate_version,
        "champion_version": champion_version,
        "holdout_fingerprint": fingerprint,
        "candidate_feature_names": list(candidate_feature_names),
        "champion_feature_names": list(champion_feature_names),
        "market_inputs": "forbidden_in_sports_score",
        "historical_prices_included": False,
        "feature_provenance": "FeatureBuilder point-in-time day-batched historical replay",
        "sample_count_is_not_model_reliability": True,
        "rows": rows,
    }
