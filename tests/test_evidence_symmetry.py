"""DIL research features must have the same P1/P2 semantics in both orientations."""
from __future__ import annotations

import pandas as pd
import pytest

from tbt.models.evidence_lab import DIL_FEATURE_NAMES
from tbt.models.symmetry import MODEL_FEATURE_CONTRACT, INVARIANT_FEATURES, swap_frame
from tbt.models.ensemble import TennisEnsemble


DIL_INVARIANTS = {
    "dil_stats_known_both", "dil_min_recent_count", "dil_min_surface_count",
    "dil_serve_known_both", "dil_return_known_both",
    "dil_second_serve_known_both", "dil_bp_save_known_both",
    "dil_bp_convert_known_both",
}


def test_candidate_dil_feature_contract_is_complete_and_orientation_safe():
    assert set(DIL_FEATURE_NAMES) <= MODEL_FEATURE_CONTRACT
    assert set(DIL_FEATURE_NAMES) & INVARIANT_FEATURES == DIL_INVARIANTS
    frame = pd.DataFrame([{
        **{name: 2.0 if name in DIL_INVARIANTS else 0.125
           for name in DIL_FEATURE_NAMES},
        "target": 1,
    }])
    swapped = swap_frame(frame)
    again = swap_frame(swapped)
    for name in DIL_FEATURE_NAMES:
        expected = 2.0 if name in DIL_INVARIANTS else -0.125
        assert swapped.loc[0, name] == pytest.approx(expected)
        assert again.loc[0, name] == pytest.approx(frame.loc[0, name])
    assert swapped.loc[0, "target"] == 0
    assert again.loc[0, "target"] == 1


def test_opt_in_model_accepts_dil_only_with_explicit_swap_contract():
    model = TennisEnsemble(feature_names=["elo_probability", *DIL_FEATURE_NAMES],
                           objective="log_loss")
    assert model.feature_names[-len(DIL_FEATURE_NAMES):] == list(DIL_FEATURE_NAMES)
    assert model.fitted is False
