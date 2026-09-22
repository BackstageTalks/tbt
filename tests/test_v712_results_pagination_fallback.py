from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'blinq-app.css').read_text(encoding='utf-8')
DATA = (ROOT / '.github' / 'workflows' / 'data.yml').read_text(encoding='utf-8')

def test_results_are_paginated_50_or_100_rows():
    assert "resultsPage:0" in APP
    assert "resultsPageSize:50" in APP
    assert "const allowedSizes=[50,100]" in APP
    assert 'id="resultsPageSize"' in APP
    assert 'id="resultsPrevPage"' in APP
    assert 'id="resultsNextPage"' in APP
    assert '.results-pagination' in CSS

def test_broken_tournament_logo_reveals_local_fallback():
    assert "data-tournament-logo" in APP
    assert "host.classList.add('logo-failed')" in APP
    assert '.hub-tournament-logo.logo-failed>.hub-logo-fallback' in CSS

def test_provider_probe_has_api_import_path():
    assert 'PYTHONPATH: api:scripts' in DATA

def test_public_live_radar_status_does_not_depend_on_insight_storage():
    fn=(ROOT / 'api' / 'function_app.py').read_text(encoding='utf-8')
    marker='def live_radar(req):'
    block=fn[fn.index(marker):fn.index('@app.route(route="v1/admin/live-radar"', fn.index(marker))]
    assert '_run_live_radar(force=False,publish=True)' in block
    run_block=fn[fn.index('def _run_live_radar'):fn.index('def _insight_plan_for_user')]
    assert 'except AdminStorageUnavailable:' in run_block and 'alert_storage_unavailable' in run_block
