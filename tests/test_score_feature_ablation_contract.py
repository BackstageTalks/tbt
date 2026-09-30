from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_score_ablation_is_read_only_parallel_and_zero_api():
    workflow = (ROOT / ".github/workflows/score-feature-ablation.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts/ablate_score_features.py").read_text(encoding="utf-8")
    request = (ROOT / ".github/score-feature-ablation-request.json").read_text(encoding="utf-8")

    assert "matrix:" in workflow
    assert "year: [2023, 2024, 2025, 2026]" in workflow
    assert "download_production_preflight_inputs.py" in workflow
    assert "ablate_score_features.py" in workflow
    assert "score-feature-ablation-latest.json" in workflow
    assert "  schedule:" not in workflow
    assert "promotion" not in workflow.lower()
    assert '"zero_provider_api_requests": true' in request

    for name in (
        "sets_7d_advantage",
        "games_7d_advantage",
        "sets_14d_advantage",
        "games_14d_advantage",
        "score_workload_known_both",
        "deciding_set_advantage",
        "deciding_set_known_both",
        "lost_set1_recovery_advantage",
        "lost_set1_recovery_known_both",
        "closing_advantage",
        "closing_known_both",
    ):
        assert f'"{name}"' in script


def test_score_ablation_uses_identical_folds_and_feature_removal_only():
    script = (ROOT / "scripts/ablate_score_features.py").read_text(encoding="utf-8")
    assert "full_features = list(FEATURE_NAMES)" in script
    assert "base_features = [name for name in FEATURE_NAMES if name not in SCORE_FEATURES]" in script
    assert "_calendar_safe_split(historical)" in script
    assert "TennisEnsemble(feature_names=full_features)" in script
    assert "TennisEnsemble(feature_names=base_features)" in script
