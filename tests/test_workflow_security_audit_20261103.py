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


def test_untrusted_inputs_do_not_interpolate_into_shell_source():
    for name in ("data.yml", "model-factory-preflight.yml", "blinq-pbp-source-vs-current-cdb.yml"):
        lines = (WF / name).read_text(encoding="utf-8").splitlines()
        in_script = False
        indent = -1
        for number, line in enumerate(lines, 1):
            start = re.match(r"^(\s*)run:\s*(.*)$", line)
            if start:
                in_script, indent = True, len(start.group(1))
            elif in_script and line.strip() and len(line) - len(line.lstrip()) <= indent:
                in_script = False
            if in_script:
                assert not re.search(r"\$\{\{\s*(?:inputs\.|github\.event\.inputs)", line), (name, number)


def test_existing_data_limits_and_cdb_single_writer_guards_unchanged():
    data = (WF / "data.yml").read_text(encoding="utf-8")
    assert "HOURLY_AUTOFILL: ${{ inputs.hourly_autofill && 'true' || 'false' }}" in data
    assert '"${HOURLY_AUTOFILL}" == "true"' in data
    assert '10#$MAX_REQUESTS > 14500' in data
    assert "tbt-crossrepo-writer-" in data
    model = (WF / "model-factory-preflight.yml").read_text(encoding="utf-8")
    assert '"$REQUEST_ID" =~ ^[0-9a-f]{24}$' in model
