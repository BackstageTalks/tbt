from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_current_mode_exists_and_reuses_current_candidate():
    workflow = (ROOT / ".github" / "workflows" / "data.yml").read_text(encoding="utf-8")
    assert "deploy-current" in workflow
    assert "env.MODE == 'deploy-current'" in workflow
    assert "inputs.mode == 'deploy-current'" in workflow
    assert "python scripts/prepare_feed.py" in workflow
    assert "python scripts/confirm_prediction_publication.py" in workflow
