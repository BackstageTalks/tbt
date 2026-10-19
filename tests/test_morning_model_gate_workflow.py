"""The morning paid refresh must never depend on an unsafe model promotion path."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/morning-refresh.yml").read_text(encoding="utf-8")
DATA_WORKFLOW = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")


def test_morning_model_gate_only_dispatches_isolated_protected_candidate():
    assert "Dispatch eligible protected candidate only (never promote)" in WORKFLOW
    assert "audit/model-promotion-readiness-latest.json" in WORKFLOW
    assert 'ready_for_metric_gate // false' in WORKFLOW
    assert 'ready_for_retrain // false' in WORKFLOW
    assert '"$ready_retrain" != "true"' in WORKFLOW
    assert "rows < 200 || days < 3" in WORKFLOW
    assert "protected-frozen-cdb-candidate.yml" in WORKFLOW
    assert "-f training_profile=top-7.2.1" in WORKFLOW


def test_morning_never_dispatches_forbidden_data_pipeline_train_or_promotion():
    assert "-f mode=train" not in WORKFLOW
    assert "-f promote=true" not in WORKFLOW
    assert "Reject training without protected backup workflow" in DATA_WORKFLOW
    assert "Reject disabled model promotion before expensive preflight" in DATA_WORKFLOW


def test_optional_gate_error_does_not_invalidate_paid_refresh():
    assert "Dispatch and supervise prediction refresh" in WORKFLOW
    assert "if ! GH_TOKEN=\"$DATA_GH_TOKEN\" gh api" in WORKFLOW
    assert "Candidate training deferred: readiness evidence unavailable." in WORKFLOW
    assert "Candidate training deferred: invalid readiness evidence." in WORKFLOW
    assert "Protected candidate dispatch failed; morning predictions remain valid." in WORKFLOW
    assert "serving champion remains unchanged" in WORKFLOW
    assert "if: steps.daily_guard.outputs.dispatch == 'true'" in WORKFLOW
    assert "vars.BLINQ_MORNING_CANDIDATE_ENABLED || 'false'" in WORKFLOW
    assert 'MORNING_CANDIDATE_ENABLED" != "true"' in WORKFLOW


def test_propline_timeout_recovery_is_present_before_morning_schedule():
    propline = (
        ROOT / "api/tbt/services/propline_live.py"
    ).read_text(encoding="utf-8")
    regression = (
        ROOT / "tests/test_propline_live.py"
    ).read_text(encoding="utf-8")
    assert "except (urllib.error.URLError, OSError):" in propline
    assert "except (RuntimeError, ValueError):" in propline
    assert "test_socket_timeout_is_a_recoverable_optional_provider_failure" in regression
    assert "test_event_timeout_skips_only_that_fixture_and_preserves_other_prices" in regression
