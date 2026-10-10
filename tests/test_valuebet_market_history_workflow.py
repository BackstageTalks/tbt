from pathlib import Path

WORKFLOW = Path(".github/workflows/valuebet-market-history.yml")


def test_valuebet_market_history_workflow_is_fail_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "link_valuebetennis_market_history.py" in text
    assert "import_offline_market_history.py" in text
    assert "Validate identity and market-feature isolation" in text
    assert "clean_market_history_marker" in text
    assert "market_data_exposed_as_model_features" in text
    assert "closing_semantics_policy" in text
    assert "sanitize_history_identities" in text
    assert "market_conflicts" in text
    assert "identity_changed" in text
    assert "valuebet-market-history-verification.json" in text


def test_valuebet_workflow_preserves_leakage_policy():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "opening_only_candidate; closing_validation_only" in text
    assert "_tbt_market_history" in text
    assert "group: tbt-crossrepo-writer-${{ github.run_id }}" in text
    assert "TBT_DATA_GH_TOKEN" in text
    assert "PRIVATE" in text


def test_valuebet_workflow_downloads_only_documented_seasons():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "for year in 2021 2022 2023 2024 2025 2026" in text
    assert "https://www.valuebetennis.com/datasets/valuebetennis-matchs-" in text
