"""The same player-swap transformation for training, evaluation and serving."""
from __future__ import annotations

import pandas as pd

from .feature_builder import FEATURE_NAMES

INVARIANT_FEATURES = {
    "rank_known_both", "travel_known", "altitude_change_known", "weather_known",
    "environment_known", "stats_known_both", "tournament_level", "best_of_five",
    "indoor", "tour_atp", "data_depth",
}


def swap_frame(frame: pd.DataFrame) -> pd.DataFrame:
    swapped = frame.copy()
    for name in FEATURE_NAMES:
        if name not in swapped:
            continue
        if name == "elo_probability":
            swapped[name] = 1.0 - frame[name]
        elif name not in INVARIANT_FEATURES:
            swapped[name] = -frame[name]
    if "target" in swapped:
        swapped["target"] = 1 - frame["target"]
    return swapped
