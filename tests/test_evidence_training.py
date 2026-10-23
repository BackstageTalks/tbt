from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from tbt.schemas import MatchRecord
from tbt.models.evidence_lab import HistoricalEvidence
from tbt.models.evidence_training import FrozenEvidenceIndex, augment_research_training_frame


T0 = datetime(2026, 9, 1, 13, tzinfo=timezone.utc)


def match(mid, a, b, winner, date, surface="hard"):
    return MatchRecord(
        match_id=mid, tour="ATP", scheduled_at=date, player1_id=a,
        player1_name=a, player2_id=b, player2_name=b, surface=surface,
        winner_id=winner, status="completed",
    )


def sample(mid, player, when, *, available=None, service_wins=65, reviewed=True):
    return HistoricalEvidence(
        canonical_match_id=mid, tour="ATP", player_id=player,
        surface="hard", completed_at=when + timedelta(hours=2),
        available_at=available or when + timedelta(hours=3),
        expected_recorded_at=when - timedelta(hours=1),
        won=True, expected_win=.5,
        service_points=100, first_in=60, first_won=service_wins - 20,
        second_won=20, opponent_service_points=100,
        opponent_first_won=36, opponent_second_won=19,
        bp_saved=4, bp_faced=5, opponent_bp_saved=3, opponent_bp_faced=7,
        reviewed_cdb_link=reviewed,
    )


def frame_for(matches):
    return pd.DataFrame([dict(match_id=m.match_id, scheduled_at=m.scheduled_at,
                              tour=m.tour.lower(), surface=m.surface) for m in matches])


def test_frozen_training_includes_only_prior_reviewed_match_stats():
    matches = [match("a-history", "A", "X", "A", T0),
               match("b-history", "B", "Y", "B", T0),
               match("target", "A", "B", "A", T0 + timedelta(days=12))]
    src = [sample("a-history", "A", T0, service_wins=65),
           sample("b-history", "B", T0, service_wins=50)]
    augmented, diag = augment_research_training_frame(frame_for(matches), matches, src)
    assert diag["rows"] == 3
    assert diag["rows_with_both_serve_return"] == 1
    assert diag["rows_with_all_five_dil_rates"] == 1
    assert augmented["match_id"].tolist() == ["a-history", "b-history", "target"]
    assert augmented.loc[0, "dil_stats_known_both"] == 0.0
    assert augmented.loc[1, "dil_stats_known_both"] == 0.0
    assert augmented.loc[2, "dil_stats_known_both"] == 1.0
    assert abs(augmented.loc[2, "dil_serve_rate_diff"]) == pytest.approx(.15)


def test_stats_published_after_prediction_never_backfill_history():
    matches = [match("a-history", "A", "X", "A", T0),
               match("b-history", "B", "Y", "B", T0),
               match("target", "A", "B", "A", T0 + timedelta(days=12))]
    src = [sample("a-history", "A", T0, available=T0 + timedelta(days=20)),
           sample("b-history", "B", T0)]
    with pytest.raises(ValueError, match="No paired PIT-qualified"):
        augment_research_training_frame(frame_for(matches), matches, src)
    result, diag = augment_research_training_frame(
        frame_for(matches), matches, src, require_stats_coverage=False)
    assert diag["rows_with_both_serve_return"] == 0
    assert result.loc[2, "dil_stats_known_both"] == 0.0


def test_index_excludes_same_calendar_day_even_with_known_order():
    index = FrozenEvidenceIndex([sample("a-history", "A", T0)])
    issued = T0 + timedelta(hours=6)
    hist = index.snapshot(tour="ATP", player_id="A", surface="hard", issued_at=issued)
    assert hist["matches_recent"] == 0
    later = index.snapshot(tour="ATP", player_id="A", surface="hard",
                           issued_at=T0 + timedelta(days=1))
    assert later["matches_recent"] == 1


def test_mismatched_frozen_frame_and_unverified_crosswalk_fail():
    matches = [match("a-history", "A", "X", "A", T0)]
    source = [sample("a-history", "A", T0)]
    bad = frame_for(matches)
    bad.loc[0, "scheduled_at"] += timedelta(days=1)
    with pytest.raises(ValueError, match="mismatches"):
        augment_research_training_frame(bad, matches, source)
    with pytest.raises(ValueError, match="link"):
        FrozenEvidenceIndex([replace(source[0], reviewed_cdb_link=False)])
    with pytest.raises(ValueError, match="Duplicate"):
        FrozenEvidenceIndex([source[0], source[0]])


def test_no_verified_observations_cannot_start_research_fit():
    ms = [match("target", "A", "B", "A", T0)]
    with pytest.raises(ValueError, match="No independently verified"):
        augment_research_training_frame(frame_for(ms), ms, [])
