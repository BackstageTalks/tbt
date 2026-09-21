from pathlib import Path


def test_ci_runs_only_canonical_tests_directory():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest tests --ignore=tests/legacy" in workflow
    assert not list(root.glob("test_*.py"))
