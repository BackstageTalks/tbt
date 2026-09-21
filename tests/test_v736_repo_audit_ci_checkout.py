from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = (ROOT / "scripts" / "audit_repo_contract.py").read_text(encoding="utf-8")

def test_repo_audit_uses_git_tracked_files_not_git_metadata():
    assert "git', '-C', str(ROOT), 'ls-files', '-z'" in AUDIT
    assert "for path in tracked_repo_files():" in AUDIT
    assert "if any(part in {'.pytest_cache', '__pycache__'}" in AUDIT
