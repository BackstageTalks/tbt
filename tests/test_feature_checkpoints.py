import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd

from tbt.models.feature_builder import FeatureBuilder
from tbt.models.feature_checkpoints import build_with_checkpoints
from tbt.schemas import MatchRecord


def _history(count=900):
    return [
        MatchRecord(
            match_id=f"ck-{i}", tour=("atp" if i % 2 else "wta"),
            scheduled_at=datetime(2023, 11, 1, tzinfo=timezone.utc) + timedelta(days=i // 3),
            player1_id=str(i % 17 + 1), player2_id=str((i + 1) % 17 + 1),
            player1_name=f"Player {i % 17 + 1}", player2_name=f"Player {(i+1) % 17 + 1}",
            winner_id=str(i % 17 + 1 if i % 3 else (i + 1) % 17 + 1),
            surface=("hard", "clay", "grass")[i % 3],
        )
        for i in range(count)
    ]


def _full(matches):
    return FeatureBuilder().build_training_frame(matches).reset_index(drop=True)


def _ck(matches, d):
    frame, info = build_with_checkpoints(FeatureBuilder, matches, d, log=lambda _s: None)
    return frame.reset_index(drop=True), info


def test_checkpointed_build_is_bit_identical_and_resumes(tmp_path):
    matches = _history()
    full = _full(matches)
    cold, info = _ck(matches, tmp_path)
    assert info["resume_year"] is None
    pd.testing.assert_frame_equal(full, cold, check_exact=True)
    warm, info = _ck(matches, tmp_path)
    assert info["resume_year"] == 2024 and info["replayed_years"] == 1
    pd.testing.assert_frame_equal(full, warm, check_exact=True)


def test_change_in_older_year_forces_earlier_replay(tmp_path):
    matches = _history()
    _ck(matches, tmp_path)
    k = next(i for i, m in enumerate(matches) if m.scheduled_at.year == 2023)
    changed = list(matches)
    changed[k] = dataclasses.replace(changed[k], player1_rank=7)
    frame, info = _ck(changed, tmp_path)
    assert info["resume_year"] == 2023
    pd.testing.assert_frame_equal(_full(changed), frame, check_exact=True)


def test_code_or_flag_change_invalidates(tmp_path):
    matches = _history(300)
    _ck(matches, tmp_path)
    frame, info = build_with_checkpoints(
        lambda: FeatureBuilder(point_weighted_quality=True), matches, tmp_path,
        log=lambda _s: None)
    assert info["resume_year"] is None
