"""Safety regression for switching only the active private shadow model."""
import json
from unittest.mock import patch

import pytest

from switch_frozen_candidate_to_shadow import (
    CANDIDATE_TAG, CHAMPION_VERSION, FROZEN_TAG, MODEL_SHA, NEW_VERSION,
    OLD_VERSION, SHADOW_TAG, digest, require_unchanged,
)
from tbt.services.shadow_evaluation import build_shadow_report


def test_shadow_switch_versions_are_explicit_and_distinct():
    assert NEW_VERSION != OLD_VERSION != CHAMPION_VERSION
    assert len(MODEL_SHA) == 64
    assert CANDIDATE_TAG != FROZEN_TAG != SHADOW_TAG


def test_new_shadow_pair_does_not_erase_or_reuse_old_shadow_evidence():
    prior = [
        {
            "match_id": "old-match-1",
            "production_model_version": CHAMPION_VERSION,
            "challenger_model_version": OLD_VERSION,
            "status": "settled",
            "scheduled_at": "2026-10-10T12:00:00+00:00",
            "target_player1_win": 1,
            "production_player1_probability": 0.60,
            "challenger_player1_probability": 0.55,
            "production_correct": True,
            "challenger_correct": True,
        }
    ]
    before = json.dumps(prior, sort_keys=True)
    old = build_shadow_report(
        prior, production_model_version=CHAMPION_VERSION,
        challenger_model_version=OLD_VERSION,
    )
    fresh = build_shadow_report(
        prior, production_model_version=CHAMPION_VERSION,
        challenger_model_version=NEW_VERSION,
    )
    assert old["cohort"]["captured"] == 1
    assert old["cohort"]["settled"] == 1
    assert fresh["cohort"]["captured"] == 0
    assert fresh["cohort"]["settled"] == 0
    assert fresh["gate"]["automatic_promotion"] is False
    assert json.dumps(prior, sort_keys=True) == before


def test_remote_release_drift_blocks_switch():
    original = {"model.joblib": (1, 250813, "sha256:" + MODEL_SHA)}
    with patch("switch_frozen_candidate_to_shadow.inventory", return_value={
        "model.joblib": (2, 250813, "sha256:" + MODEL_SHA),
    }):
        with pytest.raises(RuntimeError, match="Concurrent release modification"):
            require_unchanged(CANDIDATE_TAG, original)


def test_remote_release_unchanged_is_accepted():
    original = {"model.joblib": (1, 250813, "sha256:" + MODEL_SHA)}
    with patch("switch_frozen_candidate_to_shadow.inventory", return_value=original):
        require_unchanged(CANDIDATE_TAG, original)
