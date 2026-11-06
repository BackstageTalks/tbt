"""Production handoff contract: stale data runs cannot fake publication success."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".github/workflows/data.yml"
PREPARE = ROOT / "scripts/prepare_feed.py"


def test_stale_data_deployment_has_bounded_zero_provider_handoff():
    workflow = DATA.read_text(encoding="utf-8")
    assert "stale_handoff_run_id:" in workflow
    assert "BlinQ safe deploy handoff {0}" in workflow
    assert "id: stale_preflight" in workflow
    assert "id: stale_before_upload" in workflow
    # Both stale guards must export machine-readable state, not just an
    # explanatory notice that leaves the parent GitHub job green.
    assert workflow.count('echo "stale=true" >> "$GITHUB_OUTPUT"') == 2
    assert "stale_skip: ${{ steps.stale_preflight.outputs.stale == 'true' || steps.stale_before_upload.outputs.stale == 'true' }}" in workflow

    handoff = workflow.split("  stale_deploy_handoff:\n", 1)[1].split("  morning_presentation:\n", 1)[0]
    assert "needs.deploy.outputs.stale_skip == 'true'" in handoff
    assert "inputs.mode != 'deploy-current'" in handoff
    assert "gh workflow run data.yml" in handoff
    assert "-f mode=deploy-current -f max_requests=1" in handoff
    assert '-f stale_handoff_run_id="$GITHUB_RUN_ID"' in handoff
    assert '.display_title == $title' in handoff
    assert "conclusion\" != success" in handoff
    assert "/deployment.json?handoff=" in handoff
    assert "assert actual == os.environ['EXPECTED_SHA']" in handoff
    assert "RAPIDAPI_KEY:" not in handoff
    assert "PROPL:" not in handoff


def test_no_provider_handoff_cannot_recursively_succeed_without_deploying():
    workflow = DATA.read_text(encoding="utf-8")
    before = workflow.split("  stale_deploy_handoff:\n", 1)[0]
    assert "Fail closed if a no-provider handoff itself became stale" in before
    assert "env.BLINQ_SKIP_STALE_DEPLOY == 'true' && inputs.mode == 'deploy-current'" in before
    assert "exit 1" in before.rsplit("Fail closed if a no-provider handoff itself became stale", 1)[1]
    assert '[[ "$MODE" == "deploy-current" ]]' in workflow
    assert '[[ "$HANDOFF_RUN_ID" =~ ^[0-9]{6,20}$ ]]' in workflow

    # A stale historical runner must not spend fresh optional presentation
    # quota while a latest-main no-provider deployment is being resolved.
    morning = workflow.split("  morning_presentation:\n", 1)[1]
    assert "needs.deploy.outputs.stale_skip != 'true'" in morning


def test_production_feed_packaging_fails_closed_on_missing_candidate():
    prepare = PREPARE.read_text(encoding="utf-8")
    assert 'state == "absent" and os.getenv("BLINQ_ALLOW_EMPTY_PREDICTION_BOOTSTRAP") != "true"' in prepare
    assert "No private prediction candidate: refusing an empty production feed deployment" in prepare
    assert prepare.index('state = _prediction_asset_state(store)') < prepare.index('target.write_text(')
    # A first-ever offline bootstrap stays an explicit exception, not a default
    # for a production job carrying authenticated private release access.
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    data = DATA.read_text(encoding="utf-8")
    hotfix = (ROOT / ".github/workflows/ui-hotfix-deploy.yml").read_text(encoding="utf-8")
    for source in (ci, data, hotfix):
        assert 'test -n "$GH_TOKEN"' in source
        assert "python scripts/prepare_feed.py" in source
    assert "BLINQ_ALLOW_EMPTY_PREDICTION_BOOTSTRAP" not in ci + data + hotfix


def test_morning_supervisor_does_not_count_failed_child_as_published():
    morning = (ROOT / ".github/workflows/morning-refresh.yml").read_text(encoding="utf-8")
    assert 'if [[ "$final_status" != "completed" || "$final_conclusion" != "success" ]]' in morning
    assert 'echo "::error::Morning data.yml run' in morning
