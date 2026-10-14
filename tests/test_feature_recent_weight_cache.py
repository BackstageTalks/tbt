"""Regressions for a faster point-in-time historical feature snapshot.

No model/feature schema, same-day outcome handling or historical sample window
changes are permitted. Compare the cached entrypoint against uncached execution
using the SAME mutable state and exactly the same match ordering.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

import pandas as pd

from tbt.models.feature_builder import (
    FeatureBuilder,
    RecentPerformance,
    _RECENT_WEIGHTS_CONTEXT,
    _recent_weights,
)


def _recent():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return deque(
        [
            RecentPerformance(
                played_at=base + timedelta(days=i),
                won=float(i % 3 == 0),
                expected=0.3 + 0.005 * i,
                surface=("indoor_hard", "hard", "clay", "grass")[i % 4],
                serve_quality=None if i % 7 == 0 else 0.3 + 0.004 * i,
                return_quality=None if i % 5 == 0 else 0.2 + 0.003 * i,
                games_played=18 + i % 20,
                sets_played=2 + i % 3,
            )
            for i in range(80)
        ],
        maxlen=80,
    )


def _legacy_average(recent, now, field, half_life, *, surface=None, prior=0.5, weight=4.0):
    from tbt.models.feature_builder import stats_surface_key
    numerator, denominator = prior * weight, weight
    for item in recent:
        if surface and stats_surface_key(surface) != "unknown" and stats_surface_key(item.surface) != stats_surface_key(surface):
            continue
        age_days = max((now - item.played_at).total_seconds() / 86400.0, 0.0)
        decay = 0.5 ** (age_days / half_life)
        value = getattr(item, field)
        if value is not None:
            numerator += decay * float(value)
            denominator += decay
    return numerator / denominator if denominator else prior


def test_decayed_averages_match_original_scalar_implementation():
    recent = _recent()
    now = datetime(2026, 4, 1, 9, tzinfo=timezone.utc)
    for half_life in (30.0, 60.0, 120.0, 180.0, 240.0):
        for field in ("won", "serve_quality", "return_quality", "games_played"):
            for surface in (None, "unknown", "hard", "indoor_hard", "clay", "grass"):
                before = _legacy_average(recent, now, field, half_life, surface=surface)
                token = _RECENT_WEIGHTS_CONTEXT.set({})
                try:
                    actual = FeatureBuilder._decayed_average(
                        recent, now, field, half_life, surface=surface
                    )
                    # Repeated requests must be invariant when served from cache.
                    repeat = FeatureBuilder._decayed_average(
                        recent, now, field, half_life, surface=surface
                    )
                finally:
                    _RECENT_WEIGHTS_CONTEXT.reset(token)
                assert abs(before - actual) < 1e-13
                assert actual == repeat


def test_snapshot_cache_is_match_local_and_preserves_all_features(match_factory):
    builder = FeatureBuilder()
    for i in range(1, 29):
        match = match_factory(
            f"training-history-{i}", "A" if i % 2 else "B",
            f"O{i}", "A" if i % 2 else f"O{i}",
            day=i, surface=("hard", "clay", "indoor_hard", "grass")[i % 4],
        )
        match.stats.update({
            "p1_service_points_won": 0.30 + i * 0.005,
            "p1_return_points_won": 0.20 + i * 0.003,
            "p2_service_points_won": 0.40 + i * 0.004,
            "p2_return_points_won": 0.22 + i * 0.002,
        })
        builder.update(match)
    for surface in ("hard", "clay", "indoor_hard", "grass"):
        incoming = match_factory(
            "check-" + surface, "A", "B", None, day=29, surface=surface
        )
        before = builder._snapshot_features(incoming)
        after = builder.snapshot(incoming)
        assert list(before) == list(after)
        for key in before:
            assert abs(before[key] - after[key]) < 1e-12, (key, before[key], after[key])
        assert _RECENT_WEIGHTS_CONTEXT.get() is None


def test_full_chronological_training_frame_parity(match_factory):
    matches = [
        match_factory(
            f"history-{i}", "A" if i % 3 else "B", f"Opponent{i % 9}",
            "A" if i % 3 else f"Opponent{i % 9}",
            day=i % 28 + 1, surface=("hard", "clay", "grass")[i % 3],
        )
        for i in range(120)
    ]
    cached = FeatureBuilder().build_training_frame(matches)
    baseline_builder = FeatureBuilder()
    baseline_builder.snapshot = baseline_builder._snapshot_features
    uncached = baseline_builder.build_training_frame(matches)
    pd.testing.assert_frame_equal(cached, uncached, check_exact=False, rtol=1e-13, atol=1e-13)


def test_nested_scopes_do_not_mix_short_lived_deques():
    recent = _recent()
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)
    token = _RECENT_WEIGHTS_CONTEXT.set({})
    try:
        first = _recent_weights(recent, now, 120.0)
        second = _recent_weights(recent, now, 120.0)
        assert first is second
        other = deque(reversed(recent), maxlen=80)
        assert _recent_weights(other, now, 120.0) == tuple(reversed(first))
    finally:
        _RECENT_WEIGHTS_CONTEXT.reset(token)
    assert _RECENT_WEIGHTS_CONTEXT.get() is None


def test_training_frame_column_construction_matches_legacy(match_factory):
    matches = [match_factory(f'column-{i}', 'A', f'Opponent{i % 7}', 'A', day=i % 28 + 1, surface=('hard', 'clay', 'grass')[i % 3]) for i in range(90)]
    frame = FeatureBuilder().build_training_frame(matches)
    legacy = pd.DataFrame(frame.to_dict('records'), columns=frame.columns)
    pd.testing.assert_frame_equal(frame, legacy, check_exact=False, check_dtype=False)
    assert frame['match_id'].tolist() == legacy['match_id'].tolist()



def test_workload_windows_match_eight_legacy_sums_on_boundaries_and_invalid_values():
    from tbt.models.feature_builder import PlayerState
    now = datetime(2026, 4, 2, 13, tzinfo=timezone.utc)
    state = PlayerState()
    for days, sets, games in (
        (0.0, 0.0, 0.0), (2.0, 2.0, 20.0),
        (7.0, 3.0, 35.0), (7.00001, 1.0, 17.0),
        (14.0, 5.0, 45.0), (14.00001, 9.0, 70.0),
        (-1.0, 2.0, 19.0), (6.0, None, 42.0),
        (8.0, 4.0, None), (3.0, -2.0, -4.0),
        (5.0, float('nan'), float('inf')),
        (5.5, "bad", 12.0),
    ):
        state.recent.append(RecentPerformance(
            played_at=now-timedelta(days=days), won=1.0, expected=0.5,
            surface='hard', sets_played=sets, games_played=games,
        ))
    original = tuple(
        FeatureBuilder._metric_sum_in_window(state, now, days, field)
        for days, field in (
            (7.0, 'sets_played'), (7.0, 'games_played'),
            (14.0, 'sets_played'), (14.0, 'games_played'),
        )
    )
    assert FeatureBuilder._workload_window_totals(state, now) == original
    assert FeatureBuilder._workload_window_totals(PlayerState(), now) == (None,)*4
    # Zero is observed evidence and must not be mistaken for missing.
    zero = PlayerState(recent=deque([RecentPerformance(
        played_at=now, won=1.0, expected=0.5, surface='hard',
        sets_played=0.0, games_played=0.0,
    )], maxlen=80))
    assert FeatureBuilder._workload_window_totals(zero, now) == (0.0,)*4


def test_workload_window_optimized_training_frame_matches_original_exactly(match_factory):
    # Both builders share the same frozen chronological inputs. The control uses
    # the eight historical calls rather than the new grouped calculation.
    matches = [
        match_factory(
            f'workload-parity-{i}', 'A' if i%3 else 'B',
            f'O{i%11}', 'A' if i%3 else f'O{i%11}',
            day=i%28+1, surface=('hard','clay','grass')[i%3],
        ) for i in range(105)
    ]
    optimized = FeatureBuilder().build_training_frame(matches)
    original = FeatureBuilder()

    def legacy_workload(state, now):
        return tuple(
            original._metric_sum_in_window(state, now, days, field)
            for days, field in (
                (7.0, 'sets_played'), (7.0, 'games_played'),
                (14.0, 'sets_played'), (14.0, 'games_played'),
            )
        )

    original._workload_window_totals = legacy_workload
    reference = original.build_training_frame(matches)
    pd.testing.assert_frame_equal(optimized, reference, check_exact=True)
