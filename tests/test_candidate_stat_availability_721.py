"""7.2.1 feature-availability correction without legacy serving drift."""
from tbt.models.feature_builder import FeatureBuilder


def _snapshot(match_factory, monkeypatch, *, policy, a_serve=None, b_serve=None,
              a_return=None, b_return=None, surface=True):
    match = match_factory("stats-independent-next", "A", "B", None, day=5, surface="hard")
    builder = FeatureBuilder(independent_serve_return=policy)
    left = builder._state(match, True)
    right = builder._state(match, False)

    def stat(state, played_at, field, surface=None):
        if field not in ("serve_quality", "return_quality"):
            return None
        key = "serve" if field == "serve_quality" else "return"
        if state is left:
            return a_serve if key == "serve" else a_return
        if state is right:
            return b_serve if key == "serve" else b_return
        raise AssertionError("wrong player's statistics state")

    monkeypatch.setattr(builder, "_stat_quality", stat)
    result = builder.snapshot(match)
    return builder, result


def test_721_available_serve_survives_missing_return(match_factory, monkeypatch):
    builder, row = _snapshot(
        match_factory, monkeypatch, policy=True, a_serve=.75, b_serve=.55
    )
    assert abs(row["serve_quality_diff"] - .20) < 1e-9
    assert row["return_quality_diff"] == 0.0
    assert abs(row["surface_serve_quality_diff"] - .20) < 1e-9
    assert row["surface_return_quality_diff"] == 0.0
    assert row["stats_known_both"] == 0.0
    assert row["surface_stats_known_both"] == 0.0
    restored = FeatureBuilder.from_state(builder.export_state())
    assert restored.independent_serve_return is True


def test_721_available_return_survives_missing_serve(match_factory, monkeypatch):
    _, row = _snapshot(
        match_factory, monkeypatch, policy=True, a_return=.41, b_return=.29
    )
    assert row["serve_quality_diff"] == 0.0
    assert abs(row["return_quality_diff"] - .12) < 1e-9
    assert row["surface_serve_quality_diff"] == 0.0
    assert abs(row["surface_return_quality_diff"] - .12) < 1e-9
    assert row["stats_known_both"] == 0.0


def test_legacy_champion_keeps_exact_joint_stats_semantics(match_factory, monkeypatch):
    _, row = _snapshot(
        match_factory, monkeypatch, policy=False, a_serve=.75, b_serve=.55
    )
    assert row["serve_quality_diff"] == 0.0
    assert row["surface_serve_quality_diff"] == 0.0
    assert row["stats_known_both"] == 0.0
    restored = FeatureBuilder.from_state({"schema_version": 4, "players": {}, "h2h": []})
    assert restored.independent_serve_return is False


def test_both_complete_preserve_exact_outputs(match_factory, monkeypatch):
    kw = dict(a_serve=.75, b_serve=.55, a_return=.41, b_return=.29)
    _, new = _snapshot(match_factory, monkeypatch, policy=True, **kw)
    _, old = _snapshot(match_factory, monkeypatch, policy=False, **kw)
    for key in ("serve_quality_diff", "return_quality_diff",
                "surface_serve_quality_diff", "surface_return_quality_diff",
                "stats_known_both", "surface_stats_known_both"):
        assert new[key] == old[key]
    assert new["stats_known_both"] == 1.0


def test_missing_one_side_remains_missing_no_guessed_stats(match_factory, monkeypatch):
    _, row = _snapshot(
        match_factory, monkeypatch, policy=True, a_serve=.75, b_serve=None,
        a_return=.4, b_return=.29
    )
    assert row["serve_quality_diff"] == 0.0
    assert row["surface_serve_quality_diff"] == 0.0
    assert abs(row["return_quality_diff"] - .11) < 1e-9



def test_engine_uses_candidate_feature_policy_and_legacy_defaults():
    from tbt.services import engine

    class MockModel:
        def __init__(self, metadata):
            self.metadata = metadata

    _, context = engine.predict(MockModel({"independent_serve_return": True}), [], [],
                                return_context=True)
    assert context["builder"].independent_serve_return is True

    _, context = engine.predict(MockModel({}), [], [], return_context=True)
    assert context["builder"].independent_serve_return is False

    import pytest
    with pytest.raises(ValueError, match="feature semantics"):
        engine.predict(MockModel({"independent_serve_return": "yes"}), [], [],
                       return_context=True)
