"""Post-deployment calibration must not falsely report success."""
from pathlib import Path
import subprocess
import textwrap


def test_postdeploy_uses_real_deploy_and_correlated_readback():
    workflow = Path(".github/workflows/post-deploy-calibration-sync.yml").read_text()
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert 'SOURCE_RUN_ID: ${{ github.event.workflow_run.id }}' in workflow
    assert "CALIBRATION_POSTDEPLOY_NO_SUCCESSFUL_DEPLOY" in workflow
    assert "status=success&per_page=50" in workflow
    assert "compare/$previous_sha...$DEPLOYED_SHA" in workflow
    assert "gh run watch" in workflow
    assert "--exit-status" in workflow
    assert "CALIBRATION_POSTDEPLOY_VERIFIED" in workflow
    shell = workflow.split("        run: |\n", 1)[1]
    result = subprocess.run(
        ["bash", "-n"], input=textwrap.dedent(shell),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_watchdog_uses_immutable_deployment_revision():
    source = Path("scripts/check_live_ui_revision.py").read_text()
    assert "deployed_sha" in source
    assert '"fetch", "--no-tags", "--depth=1"' in source
    assert '"show", f"{deployed_sha}:web/{name}"' in source
    assert "expected_files = source_loader(web, live_sha)" in source
