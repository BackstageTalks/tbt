"""Memory-bounded offline calibration must preserve every match and statistic."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from tbt.schemas import MatchRecord
from tbt.models import feature_builder
from tbt.services import training


def _history(count=133):
    return [
        MatchRecord(
            match_id=f"resource-{i}", tour=("atp" if i % 2 else "wta"),
            scheduled_at=datetime(2025, 1, 1, tzinfo=timezone.utc) +
                timedelta(days=i // 3),
            player1_id=str(i % 17 + 1), player2_id=str((i + 1) % 17 + 1),
            player1_name=f"Player {i % 17 + 1}",
            player2_name=f"Player {(i+1) % 17 + 1}",
            winner_id=str(i % 17 + 1 if i % 3 else (i + 1) % 17 + 1),
            surface="hard",
        )
        for i in range(count)
    ]


def test_feature_builder_chunking_retains_all_rows_and_exact_order(monkeypatch):
    matches = _history()
    monkeypatch.setattr(feature_builder, "_TRAIN_FRAME_CHUNK_ROWS", 10000)
    single = feature_builder.FeatureBuilder().build_training_frame(matches)
    monkeypatch.setattr(feature_builder, "_TRAIN_FRAME_CHUNK_ROWS", 11)
    chunks = feature_builder.FeatureBuilder().build_training_frame(matches)
    pd.testing.assert_frame_equal(single, chunks, check_exact=True)
    assert len(chunks) == len(matches)
    assert chunks.match_id.is_unique


def test_empty_training_history_retains_frame_schema():
    empty = feature_builder.FeatureBuilder().build_training_frame([])
    assert empty.empty
    assert list(empty.columns) == feature_builder.FEATURE_NAMES + [
        "surface_history_count", "target", "match_id", "scheduled_at",
        "tour", "surface",
    ]


class Prior:
    def features_for_match(self, match, current=False):
        return {
            "atp_hist_known_both": 1.0 if match.tour == "atp" else 0.0,
            "atp_hist_rank_advantage": 3.75,
            "atp_hist_momentum_4w_known_both": 0.25,
            "atp_hist_momentum_12w_known_both": 0.5,
        }


def test_compact_rank_features_preserve_coverage_and_no_implicit_mutation():
    matches = _history(13)
    frame = pd.DataFrame({"match_id": [x.match_id for x in matches], "unmodified": 42.0})
    original = frame.copy(deep=True)
    new, report = training._augment_atp_rank_history_features(frame, matches, Prior())
    pd.testing.assert_frame_equal(frame, original)
    assert len(new) == len(frame)
    assert new.atp_hist_rank_advantage.tolist() == [3.75] * len(frame)
    assert report["rows"] == len(frame)
    assert report["known_both_rate"] == sum(x.tour == "atp" for x in matches) / len(matches)
    assert report["momentum_4w_known_both_rate"] == pytest.approx(.25)
    assert report["momentum_12w_known_both_rate"] == pytest.approx(.5)


def test_owned_frame_augments_in_place_without_losing_rows():
    matches = _history(17)
    frame = pd.DataFrame({"match_id": [x.match_id for x in matches]})
    result, report = training._augment_wta_season_features(
        frame, matches, None, inplace=True,
    )
    assert result is frame
    assert len(frame) == 17
    assert report == {"rows": 17, "known_both_rate": 0.0}
    assert frame["wta_season_stats_known_both"].eq(0.0).all()


def test_one_shot_full_fit_only_after_successful_morning_and_never_promotes():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
        ".github/workflows/one-shot-20261020-post-morning-calibration.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_run:" in workflow
    assert "BlinQ morning prediction refresh" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "2026-10-20" in workflow
    assert "protected-frozen-cdb-candidate.yml/runs?per_page=100" in workflow
    assert "-f training_profile=top-7.2.1" in workflow
    assert "-f promote=true" not in workflow
    assert "-f mode=train" not in workflow
