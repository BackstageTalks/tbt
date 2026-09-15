from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_production_preflight_builds_all_three_masters_and_training_table():
    workflow = read('.github/workflows/data.yml')
    assert 'scripts/build_player_master.py' in workflow
    assert 'scripts/build_tournament_venue_master.py' in workflow
    assert 'scripts/build_production_training_table.py' in workflow
    for name in (
        'player_master_report.json', 'tournament_master.json', 'tournament_master.csv',
        'venue_master.json', 'venue_master.csv', 'tournament_venue_report.json',
        'training_table.parquet', 'training_table_report.json',
    ):
        assert name in workflow


def test_player_master_emits_country_rank_and_identity_diagnostics():
    script = read('scripts/build_player_master.py')
    assert 'country_coverage' in script
    assert 'latest_rank_coverage' in script
    assert 'duplicate_name_groups' in script
    assert 'players_missing_country' in script


def test_production_preflight_audits_actual_statistics_inventory_and_uploads_report():
    workflow = read('.github/workflows/data.yml')
    assert 'scripts/audit_statistics_inventory.py' in workflow
    assert 'statistics_inventory_report.json' in workflow
    assert '--statistics-report .cache/tbt/production/statistics_inventory_report.json' in workflow


def test_static_environment_has_single_resumable_workflow_mode():
    workflow = read('.github/workflows/data.yml')
    assert 'environment-static' in workflow
    assert '--static-only --complete-static' in workflow
    assert '--max-requests "$MAX_REQUESTS"' in workflow
