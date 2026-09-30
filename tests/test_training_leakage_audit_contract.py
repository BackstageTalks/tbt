from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_leakage_audit_is_in_production_preflight_and_fails_closed():
    workflow = read('.github/workflows/data.yml')
    script = read('scripts/audit_training_leakage.py')
    assert 'scripts/audit_training_leakage.py' in workflow
    assert 'leakage_audit_report.json' in workflow
    assert 'raise SystemExit("Production leakage audit failed:' in script
    assert 'historical_posthoc_weather_never_marked_training_eligible' in script
    assert 'model_feature_contract_has_no_target_or_result_fields' in script
    assert 'training_frame_chronological' in script


def test_leakage_policy_reuses_rank_provenance_and_point_in_time_feature_builder():
    script = read('scripts/audit_training_leakage.py')
    feature = read('api/tbt/models/feature_builder.py')
    shim = read('api/tbt/services/feature_builder.py')
    assert '_enforce_rank_provenance' in script
    assert 'Snapshot every match before applying any result from this' in feature
    assert 'current_match_statistics_update_state_only_after_snapshot' in script
    assert 'from ..models.feature_builder import *' in shim


def test_every_train_runs_fail_closed_leakage_preflight_and_can_defer_promotion():
    workflow = read('.github/workflows/data.yml')
    pipeline = read('scripts/pipeline.py')
    assert 'if [[ "$MODE" == train ]]; then' in workflow
    assert 'python scripts/download_production_preflight_inputs.py' in workflow
    assert 'python scripts/audit_training_leakage.py \\' in workflow
    assert '.cache/tbt/production/leakage_audit_report.json' in workflow
    assert 'eligibility_reason == "no_eligible_unseen_evaluation_rows"' in pipeline
    assert 'decision_status = "deferred"' in pipeline
    assert 'Promotion deferred until new unseen evaluation rows exist' in pipeline
    assert 'report["promotion_decision"] = decision' in pipeline


def test_refresh_and_train_publish_model_promotion_readiness():
    workflow = read('.github/workflows/data.yml')
    assert "Update model promotion readiness" in workflow
    assert "scripts/model_promotion_readiness.py" in workflow
    assert "--minimum-gate-rows 200" in workflow
    assert "--target-rows 1000" in workflow
    assert "--minimum-days 3" in workflow
    assert "audit/model-promotion-readiness-latest.json" in workflow
