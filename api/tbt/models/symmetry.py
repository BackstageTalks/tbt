"""The same player-swap transformation for training, evaluation and serving."""
from __future__ import annotations

import pandas as pd

from ..data.atp_leaderboards import ATP_LEADERBOARD_FEATURE_NAMES
from ..data.court_speed import COURT_SPEED_FEATURE_NAMES
from ..data.wta_season_stats import WTA_SEASON_FEATURE_NAMES
from .feature_builder import FEATURE_NAMES

MODEL_FEATURE_CONTRACT = set(FEATURE_NAMES) | set(COURT_SPEED_FEATURE_NAMES)

INVARIANT_FEATURES = {
    "rank_known_both", "season_yelo_known_both", "travel_known", "altitude_change_known", "weather_known",
    "environment_known", "stats_known_both", "surface_stats_known_both",
    "rich_charting_known_both", "surface_h2h_known", "score_workload_known_both",
    "deciding_set_known_both",
    "lost_set1_recovery_known_both", "closing_known_both",
    "round_form_known_both", "tournament_history_known_both",
    "tournament_level", "best_of_five", "indoor", "tour_atp", "data_depth",
    "atp_leaderboard_known_both", "atp_surface_leaderboard_known_both",
    "wta_season_stats_known_both",
    "court_speed_prior", "court_speed_current",
    "court_speed_delta_vs_venue_history", "court_speed_known",
}

SWAP_PAIRS = {
    "court_speed_mismatch_player1": "court_speed_mismatch_player2",
    "court_speed_mismatch_player2": "court_speed_mismatch_player1",
}


def swap_frame(frame: pd.DataFrame) -> pd.DataFrame:
    swapped = frame.copy()
    for name in MODEL_FEATURE_CONTRACT:
        if name not in swapped:
            continue
        if name in SWAP_PAIRS:
            swapped[name] = frame[SWAP_PAIRS[name]]
        elif name in {"elo_probability", "season_yelo_probability"}:
            swapped[name] = 1.0 - frame[name]
        elif name not in INVARIANT_FEATURES:
            swapped[name] = -frame[name]
    if "target" in swapped:
        swapped["target"] = 1 - frame["target"]
    return swapped
