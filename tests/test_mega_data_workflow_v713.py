from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/data.yml').read_text(encoding='utf-8')
SCRIPT = (ROOT / 'scripts/run_mega_data.py').read_text(encoding='utf-8')


def test_mega_data_mode_is_exposed_and_serialized():
    assert 'mega-data' in WORKFLOW
    assert 'group: tbt-history-data-writer' in WORKFLOW
    assert 'python scripts/run_mega_data.py' in WORKFLOW


def test_mega_data_has_one_global_budget_and_expected_phases():
    assert '--max-requests "$MAX_REQUESTS"' in WORKFLOW
    for token in ('provider-probe', 'history', 'ace-statistics', 'sg-scores', 'statistics'):
        assert token in SCRIPT
    assert 'requests_unused' in SCRIPT
    assert 'collector_model_available' in SCRIPT


def test_targeted_jobs_write_request_summaries_for_budget_rollover():
    ace = (ROOT / 'scripts/enrich_ace_history.py').read_text(encoding='utf-8')
    sg = (ROOT / 'scripts/enrich_sg_history.py').read_text(encoding='utf-8')
    assert 'ace_run_summary.json' in ace
    assert 'sg_run_summary.json' in sg
