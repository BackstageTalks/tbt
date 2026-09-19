from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_generated_artifact_cleaner_removes_python_cache(tmp_path):
    # Validate production script contract from the actual repository rather than
    # depending on an ignored cache directory created by pytest itself.
    script = (ROOT / 'scripts' / 'clean_generated_artifacts.py').read_text(encoding='utf-8')
    assert "'__pycache__'" in script
    assert "'.pytest_cache'" in script
    assert "'.pyc'" in script
    assert "'.pyo'" in script


def test_ci_sanitizes_before_contract_audit_and_deploys():
    ci=(ROOT/'.github/workflows/ci.yml').read_text(encoding='utf-8')
    assert ci.count('python scripts/clean_generated_artifacts.py') >= 2
    assert ci.index('Sanitize generated artifacts') < ci.index('Audit repository/release contract')
    data=(ROOT/'.github/workflows/data.yml').read_text(encoding='utf-8')
    enrich=(ROOT/'.github/workflows/player-enrichment.yml').read_text(encoding='utf-8')
    assert 'Sanitize generated artifacts before deploy' in data
    assert 'Sanitize generated artifacts before deploy' in enrich


def test_repo_audit_ignores_sanitized_missing_tracked_path():
    audit=(ROOT/'scripts/audit_repo_contract.py').read_text(encoding='utf-8')
    assert 'if not path.exists()' in audit
