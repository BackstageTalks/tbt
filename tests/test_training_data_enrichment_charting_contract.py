from pathlib import Path

WORKFLOW = Path(".github/workflows/training-data-enrichment.yml")
PINNED_CHARTING_COMMIT = "1813a1309b7ed7ebf1c7e884b32bf675d00e4edf"


def test_training_enrichment_integrates_pinned_match_charting_fail_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "JeffSackmann/tennis_MatchChartingProject.git" in text
    assert text.count(PINNED_CHARTING_COMMIT) >= 3
    assert "--charting-zip .cache/tbt/enrichment/charting-root.zip" in text
    assert ".cache/tbt/enrichment/charting-link/auto_linked.jsonl" in text
    assert ".cache/tbt/enrichment/charting-import/report.json" in text
    assert '"charting_import":enrichment.get("charting_import")' in text


def test_training_enrichment_keeps_charting_inside_existing_safety_and_readback_path():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'import_keys=("tml_import","wta_import","sackmann_import","charting_import","atp_pbp_import")' in text
    assert 'sanitize_history_identities(matches)' in text
    assert 'audit_training_leakage.py' in text
    assert 'Final persisted training DB readback verification' in text
    assert 'No model promotion' not in text  # policy belongs in request; workflow itself performs none
    assert "TENNIS_API" not in text
    assert "RAPIDAPI" not in text
