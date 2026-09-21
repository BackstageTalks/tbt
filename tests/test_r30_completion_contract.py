from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def test_r30_workflow_exposes_production_audit_and_results_rebuild():
    workflow = read('.github/workflows/data.yml')
    assert 'production-audit' in workflow
    assert 'results-rebuild' in workflow
    assert 'scripts/audit_production_predictions.py' in workflow
    assert 'scripts/rebuild_results_history.py' in workflow


def test_r30_rolling_windows_feed_single_model_success_card_only():
    app = read('web/app.js')
    engine = read('api/tbt/services/engine.py')
    assert 'PERFORMANCE_WINDOWS_DAYS = (3, 7, 10, 14, 30)' in engine
    assert '"dashboard_model_success"' in engine
    assert 'dashboardBest=state.feed?.dashboard_model_success' in app
    assert 'dailyHubPerformanceText' not in app
    assert 'market-card-performance' not in app


def test_r30_live_radar_diagnostics_and_relaxed_defaults_are_present():
    worker = read('api/tbt/services/live_comeback.py')
    api = read('api/function_app.py')
    assert 'DEFAULT_MIN_PROBABILITY = .68' in worker
    assert 'DEFAULT_MAX_ODDS = 1.49' in worker
    assert 'prime_total' in api
    assert 'prime_eligible' in api
    assert 'provider_skipped_reason' in api


def test_r30_projection_models_and_publication_identity_are_current():
    ace = read('api/tbt/services/ace_selection.py')
    sg = read('api/tbt/services/sg_selection.py')
    pipeline = read('scripts/pipeline.py')
    assert 'ace-count-projection-v4' in ace
    assert 'walk_forward_isotonic_conservative' in ace
    assert 'sets-games-projection-v3' in sg
    assert '"projection_scope": "match_total"' in sg
    assert '_projection_presentation_integrity' in pipeline
