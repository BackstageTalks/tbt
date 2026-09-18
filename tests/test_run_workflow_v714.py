from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = (ROOT / '.github/workflows/data.yml').read_text(encoding='utf-8')
ENV = (ROOT / '.github/workflows/environment-enrichment.yml').read_text(encoding='utf-8')
MEGA = (ROOT / 'scripts/run_mega_data.py').read_text(encoding='utf-8')
PROBE = (ROOT / 'scripts/probe_tennis_provider.py').read_text(encoding='utf-8')


def test_mega_data_prioritizes_statistics_then_sg_then_ace():
    assert MEGA.index('"statistics-primary"') < MEGA.index('"sg-scores"') < MEGA.index('"ace-statistics"')
    assert '"statistics-tail"' in MEGA
    assert 'statistics_inventory_after.json' in MEGA
    assert '.cache/tbt/mega-data/statistics_inventory_after.json' in DATA


def test_mega_data_keeps_history_small_and_one_global_cap():
    assert 'min(700' in MEGA
    assert 'int(total * 0.05)' in MEGA
    assert 'mega-data max-requests must be 500..12000' in MEGA
    assert 'requests_unused' in MEGA


def test_provider_probe_captures_actual_stat_item_names():
    assert 'stat_item_names' in PROBE
    assert 'unsupported_item_names' in PROBE
    assert 'supported_rate_alias_hits' in PROBE
    assert 'sample_items' in PROBE
    assert 'live_odds_samples' in PROBE
    assert 'second_set' in PROBE


def test_environment_force_static_no_longer_adds_complete_static():
    # Force and complete-static are mutually exclusive in the Python CLI. The
    # workflow must add complete-static only in the final non-force branch.
    assert 'if [[ "${{ inputs.force }}" == "true" ]]; then' in ENV
    force_pos = ENV.index('if [[ "${{ inputs.force }}" == "true" ]]; then')
    elif_retry = ENV.index('elif [[ "${{ inputs.retry_unresolved }}" == "true" ]]', force_pos)
    complete_pos = ENV.index('ARGS+=(--complete-static)', elif_retry)
    assert force_pos < elif_retry < complete_pos
    assert '--max-requests "${{ inputs.max_requests }}"' in ENV
    assert 'default: "12000"' in ENV
    assert 'default: "0"' in ENV


def test_environment_report_is_uploaded():
    assert 'Upload environment run report' in ENV
    assert '.cache/tbt/history/environment_enrichment_report.json' in ENV


def test_mega_data_repairs_history_before_spending_on_enrichment():
    assert MEGA.index('"history"') < MEGA.index('"statistics-primary"')
    assert 'history_download_report.json' in MEGA
    assert 'statistics_inventory_before.json' in MEGA
    assert 'history_audit_after.json' in MEGA


def test_mega_data_uses_large_history_safety_cap_but_rolls_unused_budget_forward():
    assert 'min(700' in MEGA
    assert 'int(total * 0.05)' in MEGA
    assert 'int(enrich_total * 0.35)' in MEGA
    assert 'int(enrich_total * 0.23)' in MEGA
    assert 'planned["statistics_primary"] + carry' in MEGA
    assert '"refresh": refresh' in MEGA
    assert 'pipeline.py", "refresh"' in MEGA
