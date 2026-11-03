"""CDB request-only pushes must not redeploy an unchanged UI/API."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_main_ci_ignores_only_two_verified_cdb_request_markers():
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    pushes = ci.split("\n  push:", 1)[1].split("\n  pull_request:", 1)[0]
    for marker in (
        ".github/cdb-sackmann-bp-request.json",
        ".github/cdb-service-complements-audit-request.json",
    ):
        assert pushes.count(f"- '{marker}'") == 1
    assert "paths-ignore:" in pushes
    assert "'.github/*'" not in pushes
    assert "'.github/**/*.json'" not in pushes
    # Mixed source + request changes must still trigger ordinary application CI.
    assert "  pull_request:" in ci
    assert "  workflow_dispatch:" in ci
    assert "cancel-in-progress: true" in ci


def test_guarded_cdb_workflows_still_receive_their_own_marker_push():
    expected = {
        "cdb-sackmann-bp-guarded.yml": ".github/cdb-sackmann-bp-request.json",
        "cdb-service-complement-audit.yml": ".github/cdb-service-complements-audit-request.json",
    }
    for workflow, marker in expected.items():
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert "  push:" in text, workflow
        assert marker in text, workflow
        assert "branches: [main]" in text, workflow
    bp = (WORKFLOWS / "cdb-sackmann-bp-guarded.yml").read_text(encoding="utf-8")
    assert "cdb_global_writer_lock.py acquire" in bp
    audit = (WORKFLOWS / "cdb-service-complement-audit.yml").read_text(encoding="utf-8")
    assert "write_authorized" in audit and "False" in audit
