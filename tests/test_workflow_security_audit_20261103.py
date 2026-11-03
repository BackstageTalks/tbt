"""Guard audited workflow shell inputs and external action provenance."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
AZURE = "Azure/static-web-apps-deploy@1a947af9992250f3bc2e68ad0754c0b0c11566c9"
GOOGLE = "google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093"


def test_verified_action_shas_in_all_affected_workflows():
    for name in ("ci.yml", "data.yml", "player-enrichment.yml", "ui-hotfix-deploy.yml"):
        value = (WF / name).read_text(encoding="utf-8")
        assert AZURE in value, name
        assert "Azure/static-web-apps-deploy@v1" not in value
    google = (WF / "blinq-private-drive-cdb-audit-bridge.yml").read_text(encoding="utf-8")
    assert GOOGLE in google
    assert "google-github-actions/auth@v3" not in google


_UNTRUSTED_SHELL_EXPRESSION = re.compile(
    r"\$\{\{\s*(?:inputs\.|github\.event\.|github\.head_ref\b|github\.ref_name\b)"
)


def _risky_shell_lines(lines):
    """Check both 'run:' and '- run:', but not surrounding step env fields."""
    in_script = False
    run_key_indent = -1
    for number, line in enumerate(lines, 1):
        match = re.match(r"^\s*(?:-\s*)?run:\s*(.*)$", line)
        if match:
            in_script = True
            run_key_indent = line.index("run:")
        elif in_script and line.strip():
            indentation = len(line) - len(line.lstrip())
            if indentation <= run_key_indent:
                in_script = False
        if in_script and _UNTRUSTED_SHELL_EXPRESSION.search(line):
            yield number


def test_untrusted_workflow_event_and_dispatch_inputs_stay_out_of_shell_source():
    paths = sorted(WF.glob("*.yml")) + sorted(WF.glob("*.yaml"))
    assert len(paths) >= 150, "Workflow audit unexpectedly missing files"
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        violations = list(_risky_shell_lines(lines))
        assert not violations, (path.name, violations)


def test_shell_interpolation_scanner_recognizes_inline_and_block_run():
    sample = [
        "  - name: Demonstration",
        "    env:",
        "      SAFE_AS_ENV: ${{ github.event.pull_request.title }}",
        "    run: |",
        '      echo "safe $SAFE_AS_ENV"',
        "  - run: echo '${{ inputs.untrusted }}'",
        "  - run: |",
        "      python -c 'print(1)'",
        "      echo '${{ github.head_ref }}'",
    ]
    assert list(_risky_shell_lines(sample)) == [6, 9]


def test_existing_data_limits_and_cdb_single_writer_guards_unchanged():
    data = (WF / "data.yml").read_text(encoding="utf-8")
    assert "HOURLY_AUTOFILL: ${{ inputs.hourly_autofill && 'true' || 'false' }}" in data
    assert '"${HOURLY_AUTOFILL}" == "true"' in data
    assert '10#$MAX_REQUESTS > 14500' in data
    assert "tbt-crossrepo-writer-" in data
    model = (WF / "model-factory-preflight.yml").read_text(encoding="utf-8")
    assert '"$REQUEST_ID" =~ ^[0-9a-f]{24}$' in model


def test_production_ci_dependency_actions_pinned_to_commits():
    ci = (WF / "ci.yml").read_text(encoding="utf-8")
    expected = {
        "actions/checkout": ("11bd71901bbe5b1630ceea73d27597364c9", 2),
        "actions/setup-python": ("a26af69be951a213d495a4c3e4e4022e16d87065", 2),
        "actions/setup-node": ("49933ea5288caeca8642d1e84afbd3f7d6820020", 2),
        "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", 1),
    }
    for action, (sha, occurrences) in expected.items():
        assert ci.count(f"uses: {action}@{sha}") == occurrences
        assert not re.search(rf"uses:\s+{re.escape(action)}@v\d+\b", ci)
    assert AZURE in ci
