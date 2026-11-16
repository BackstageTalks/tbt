from types import SimpleNamespace

import numpy as np
import pandas as pd

from tbt.services.training import _candidate_time_partitions, _split_by_date, _eligible_evaluation


def fixture():
    days = pd.date_range("2024-01-01", periods=500, tz="UTC")
    frame = pd.DataFrame({"scheduled_at": np.repeat(days, 10),
                          "match_id": np.arange(5000), "target": np.arange(5000) % 2})
    champion = SimpleNamespace(metadata={"history_end": days[470].isoformat()})
    return frame, champion, days


def test_reclaim_recent_history_without_changing_eligible_holdout():
    frame, champion, days = fixture()
    old_train, old_cal, old_test = _split_by_date(frame, .70, .15)
    expected, _ = _eligible_evaluation(old_test, champion, as_of=days[-1])
    train, cal, test, reason = _candidate_time_partitions(
        frame, "top-7.2.1", champion, as_of=days[-1])
    assert reason is None
    pd.testing.assert_frame_equal(test, expected)
    assert cal.scheduled_at.max() == days[470]
    assert old_cal.scheduled_at.max() < cal.scheduled_at.max()
    assert train.scheduled_at.max() < cal.scheduled_at.min() < test.scheduled_at.min()
    assert set(train.match_id) | set(cal.match_id) == set(frame.loc[frame.scheduled_at <= days[470], "match_id"])
    assert not set(cal.match_id) & set(test.match_id)
    assert not set(train.match_id) & set(test.match_id)
    assert test.scheduled_at.max() < days[-1]  # Current UTC day excluded.
    assert len(train) + len(cal) > len(old_train) + len(old_cal)


def test_unknown_provenance_cannot_move_calibration_boundary():
    frame, _, days = fixture()
    old_train, old_cal, _ = _split_by_date(frame, .70, .15)
    train, cal, test, reason = _candidate_time_partitions(
        frame, "top-7.2.1", SimpleNamespace(metadata={}), as_of=days[-1])
    assert reason == "production_history_cutoff_unknown"
    assert test.empty
    pd.testing.assert_frame_equal(train, old_train)
    pd.testing.assert_frame_equal(cal, old_cal)


def test_boundaries_do_not_depend_on_labels_and_other_profiles_unchanged():
    frame, champion, days = fixture()
    a = _candidate_time_partitions(frame, "top-7.2.1", champion, as_of=days[-1])
    changed = frame.copy()
    changed["target"] = 1 - changed.target
    b = _candidate_time_partitions(changed, "top-7.2.1", champion, as_of=days[-1])
    for left, right in zip(a[:3], b[:3]):
        assert list(left.match_id) == list(right.match_id)
    old_train, old_cal, _ = _split_by_date(frame, .70, .15)
    for profile in ("standard", "accuracy-7.2.2"):
        train, cal, _, _ = _candidate_time_partitions(frame, profile, champion, as_of=days[-1])
        pd.testing.assert_frame_equal(train, old_train)
        pd.testing.assert_frame_equal(cal, old_cal)


def test_consumed_promotion_days_stay_out_of_holdout():
    frame, champion, days = fixture()
    history = [{"holdout_period": {"end": days[480].isoformat()},
                "promotion_requested": True}]
    _, cal, test, reason = _candidate_time_partitions(
        frame, "top-7.2.1", champion, history, as_of=days[-1])
    assert reason is None
    assert cal.scheduled_at.max() == days[480]
    assert test.scheduled_at.min() == days[481]
