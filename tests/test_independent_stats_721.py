"""Serve/return must be independent in opt-in candidate feature snapshots."""
import pandas as pd
import pytest

from tbt.models.feature_builder import FeatureBuilder, INDEPENDENT_STATS_FEATURE_NAMES
from tbt.models.symmetry import swap_frame
from tbt.services.training import PRODUCTION_FEATURE_NAMES


def test_missing_return_does_not_erase_available_serve(match_factory):
    builder = FeatureBuilder()
    match = match_factory("separate-serve", "A", "B", None, day=4, surface="hard")
    a, b = builder.players["A"], builder.players["B"]

    def stats(player, at, kind, surface=None):
        if kind == "serve_quality":
            return (0.73 if player is a else 0.43)
        return None

    builder._stat_quality = stats
    features = builder.snapshot(match)

    # Historic production feature remains untouched; 7.2.1 gets true signal.
    assert features["serve_quality_diff"] == 0.0
    assert features["return_quality_diff"] == 0.0
    assert features["stats_known_both"] == 0.0
    assert features["serve_independent_diff"] == pytest.approx(0.30)
    assert features["return_independent_diff"] == 0.0
    assert features["serve_independent_known_both"] == 1.0
    assert features["return_independent_known_both"] == 0.0
    assert features["surface_serve_independent_diff"] == pytest.approx(0.30)
    assert features["surface_return_independent_known_both"] == 0.0


def test_opposite_missing_serve_does_not_erase_return(match_factory):
    builder = FeatureBuilder()
    match = match_factory("separate-return", "A", "B", None, day=4)
    a, b = builder.players["A"], builder.players["B"]
    builder._stat_quality = (
        lambda player, at, kind, surface=None:
        (0.6 if player is a else 0.45) if kind == "return_quality" else None
    )
    f = builder.snapshot(match)
    assert f["return_independent_diff"] == pytest.approx(.15)
    assert f["serve_independent_diff"] == 0.0
    assert f["return_independent_known_both"] == 1.0
    assert f["serve_independent_known_both"] == 0.0


def test_new_feature_symmetry_and_production_feature_schema_unchanged(match_factory):
    builder = FeatureBuilder()
    match = match_factory("sym-separate", "A", "B", None, day=4)
    snapshot = builder.snapshot(match)
    frame = pd.DataFrame([snapshot])
    swapped = swap_frame(frame)
    for name in INDEPENDENT_STATS_FEATURE_NAMES:
        assert name in frame.columns
        assert name not in PRODUCTION_FEATURE_NAMES
        if name.endswith("_known_both"):
            assert swapped[name][0] == frame[name][0]
        else:
            assert swapped[name][0] == -frame[name][0]
