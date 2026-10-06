from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/morning-refresh.yml").read_text(encoding="utf-8")


def test_morning_refresh_dispatches_model_gate_only_when_readiness_is_sufficient():
    assert "Dispatch guarded model promotion gate when enough unseen data exists" in WORKFLOW
    assert "audit/model-promotion-readiness-latest.json" in WORKFLOW
    assert 'ready_for_metric_gate // false' in WORKFLOW
    assert 'ready_for_retrain // false' in WORKFLOW
    assert '"$rows" -lt 200' in WORKFLOW
    assert '"$days" -lt 3' in WORKFLOW


def test_guarded_model_gate_uses_train_without_provider_budget():
    assert "-f mode=train" in WORKFLOW
    assert "-f max_requests=1" in WORKFLOW
    assert "-f promote=true" in WORKFLOW
    assert "Model promotion gate deferred; current champion remains unchanged." in WORKFLOW
