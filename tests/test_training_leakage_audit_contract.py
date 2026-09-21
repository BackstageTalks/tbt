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
