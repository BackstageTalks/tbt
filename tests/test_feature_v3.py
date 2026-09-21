from __future__ import annotations

from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder


def _score(match, *, total_sets, total_games, p1_first, p2_first, p1_second, p2_second, deciding):
    match.stats.update(
        {
            "total_sets": float(total_sets),
            "total_games": float(total_games),
            "p1_first_set_won": float(p1_first),
            "p2_first_set_won": float(p2_first),
            "p1_second_set_won": float(p1_second),
            "p2_second_set_won": float(p2_second),
            "deciding_set": float(deciding),
        }
    )
    return match


def _quality(match, p1_serve, p1_return, p2_serve, p2_return):
    match.stats.update(
        {
            "p1_service_points_won": float(p1_serve),
            "p1_return_points_won": float(p1_return),
            "p2_service_points_won": float(p2_serve),
            "p2_return_points_won": float(p2_return),
        }
    )
    return match


def test_v3_feature_schema_contains_point_in_time_history_features():
    expected = {
        "surface_serve_quality_diff",
        "surface_return_quality_diff",
        "surface_h2h_advantage",
        "sets_7d_advantage",
        "games_7d_advantage",
        "deciding_set_advantage",
        "lost_set1_recovery_advantage",
        "closing_advantage",
        "round_form_diff",
        "tournament_history_advantage",
    }
    assert expected.issubset(set(FEATURE_NAMES))


def test_surface_stats_do_not_mix_surfaces(match_factory):
    builder = FeatureBuilder()
    hard_a = _quality(match_factory("hard-a", "A", "X", "A", day=1, surface="hard"), .80, .35, .55, .30)
    hard_b = _quality(match_factory("hard-b", "B", "Y", "Y", day=1, surface="hard"), .50, .25, .75, .35)
    clay_a = _quality(match_factory("clay-a", "A", "Z", "Z", day=2, surface="clay"), .40, .20, .75, .40)
    clay_b = _quality(match_factory("clay-b", "B", "Q", "B", day=2, surface="clay"), .85, .40, .45, .20)
    for match in (hard_a, hard_b, clay_a, clay_b):
        builder.update(match)

    upcoming = match_factory("next", "A", "B", None, day=4, surface="hard")
    snap = builder.snapshot(upcoming)
    assert snap["surface_stats_known_both"] == 1.0
    assert snap["surface_serve_quality_diff"] > 0


def test_score_workload_prefers_less_loaded_player(match_factory):
    builder = FeatureBuilder()
    a = _score(match_factory("a", "A", "X", "A", day=1), total_sets=2, total_games=18,
               p1_first=1, p2_first=0, p1_second=1, p2_second=0, deciding=0)
    b1 = _score(match_factory("b1", "B", "Y", "B", day=1), total_sets=3, total_games=31,
                p1_first=0, p2_first=1, p1_second=1, p2_second=0, deciding=1)
    b2 = _score(match_factory("b2", "B", "Z", "B", day=2), total_sets=3, total_games=29,
                p1_first=1, p2_first=0, p1_second=0, p2_second=1, deciding=1)
    for match in (a, b1, b2):
        builder.update(match)

    upcoming = match_factory("next", "A", "B", None, day=5)
    snap = builder.snapshot(upcoming)
    assert snap["score_workload_known_both"] == 1.0
    assert snap["sets_7d_advantage"] > 0
    assert snap["games_7d_advantage"] > 0


def test_surface_h2h_is_separate_and_shrunk(match_factory):
    builder = FeatureBuilder()
    builder.update(match_factory("h-hard", "A", "B", "A", day=1, surface="hard"))
    builder.update(match_factory("h-clay", "A", "B", "B", day=2, surface="clay"))

    hard = builder.snapshot(match_factory("hard-next", "A", "B", None, day=3, surface="hard"))
    clay = builder.snapshot(match_factory("clay-next", "A", "B", None, day=3, surface="clay"))
    assert hard["surface_h2h_advantage"] > 0
    assert clay["surface_h2h_advantage"] < 0
    assert hard["surface_h2h_known"] > 0


def test_feature_state_v1_remains_loadable():
    legacy = {"schema_version": 1, "players": {}, "h2h": []}
    restored = FeatureBuilder.from_state(legacy)
    assert restored.export_state()["schema_version"] == 2


def test_serving_respects_legacy_artifact_feature_schema(match_factory):
    from tbt.services import engine

    class LegacyModel:
        version = "legacy"
        feature_names = ["elo_diff", "elo_probability", "data_depth"]

        def __init__(self):
            self.columns = None

        def predict_proba(self, frame):
            self.columns = list(frame.columns)
            return [0.6 for _ in range(len(frame))]

    history = [match_factory("past", "A", "C", "A", day=1)]
    future = match_factory("future", "A", "B", None, day=5)
    model = LegacyModel()
    rows = engine.predict(model, history, [future], now=future.scheduled_at.replace(day=4))
    assert rows
    assert model.columns == model.feature_names
