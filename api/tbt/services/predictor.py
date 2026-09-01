from __future__ import annotations

from datetime import timezone

import pandas as pd

from ..models.ensemble import TennisEnsemble
from ..models.feature_builder import FEATURE_NAMES, FeatureBuilder
from ..schemas import MatchRecord, PredictionRecord
from ..utils import clamp, utcnow


def _frame(features: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{name: float(features.get(name, 0.0)) for name in FEATURE_NAMES}])


def _confidence_band(probability: float, data_depth: float) -> str:
    winner_p = max(probability, 1.0 - probability)
    if winner_p >= 0.76 and data_depth >= 0.45:
        return "high"
    if winner_p >= 0.63 and data_depth >= 0.20:
        return "medium"
    return "low"


def _signals(match: MatchRecord, features: dict[str, float]) -> list[dict]:
    candidates = [
        ("Surface strength", features["surface_elo_diff"], 0.12),
        ("Overall strength", features["elo_diff"], 0.12),
        ("Official ranking", features["rank_advantage"], 0.45),
        ("Recent form", features["recent_form_diff"], 0.08),
        ("Opponent-adjusted form", features["opponent_adjusted_form_diff"], 0.05),
        ("Surface form", features["surface_form_diff"], 0.08),
        ("Head-to-head", features["h2h_advantage"], 0.15),
        ("Rest / workload", features["rest_advantage"] + features["layoff_advantage"] * 0.25, 0.35),
    ]
    ranked = sorted(candidates, key=lambda item: abs(item[1] / item[2]), reverse=True)
    result: list[dict] = []
    for label, value, scale in ranked:
        if abs(value) < scale:
            continue
        favours_p1 = value > 0
        result.append(
            {
                "factor": label,
                "favours_player_id": match.player1_id if favours_p1 else match.player2_id,
                "favours_player_name": match.player1_name if favours_p1 else match.player2_name,
                "strength": "strong" if abs(value) >= scale * 2.0 else "moderate",
            }
        )
        if len(result) == 4:
            break
    return result


def predict_matches(
    model: TennisEnsemble,
    history: list[MatchRecord],
    upcoming: list[MatchRecord],
) -> list[PredictionRecord]:
    if not upcoming:
        return []
    builder = FeatureBuilder()
    earliest = min(match.scheduled_at for match in upcoming)
    builder.replay(history, before=earliest)

    predictions: list[PredictionRecord] = []
    for match in sorted(upcoming, key=lambda m: (m.scheduled_at, m.match_id)):
        forward = builder.snapshot(match)
        reverse = builder.snapshot(match.swapped())
        p_forward = float(model.predict_proba(_frame(forward))[0])
        p_reverse = float(model.predict_proba(_frame(reverse))[0])
        # Enforce tennis symmetry: P(A beats B) = 1 - P(B beats A).
        p1 = clamp(0.5 * (p_forward + (1.0 - p_reverse)), 0.01, 0.99)
        p2 = 1.0 - p1
        p1_wins = p1 >= 0.5
        winner_id = match.player1_id if p1_wins else match.player2_id
        winner_name = match.player1_name if p1_wins else match.player2_name
        confidence = max(p1, p2) * 100.0
        predictions.append(
            PredictionRecord(
                match_id=match.match_id,
                model_version=model.version,
                generated_at=utcnow(),
                player1_probability=p1,
                player2_probability=p2,
                predicted_winner_id=winner_id,
                predicted_winner_name=winner_name,
                confidence_pct=round(confidence, 2),
                confidence_band=_confidence_band(p1, forward["data_depth"]),
                features={name: round(float(forward[name]), 6) for name in FEATURE_NAMES},
                signals=_signals(match, forward),
                fixture=match,
            )
        )
    return predictions
