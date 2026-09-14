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


def test_production_preflight_uses_script_not_fragile_shell_heredoc():
    workflow = read('.github/workflows/data.yml')
    assert 'scripts/download_production_preflight_inputs.py' in workflow
    production_block = workflow.split('elif [[ "$MODE" == production-preflight ]]', 1)[1].split('else', 1)[0]
    assert "python - <<'PY'" not in production_block
    helper = read('scripts/download_production_preflight_inputs.py')
    assert "ReleaseStore(repository, 'tbt-data-v1'" in helper
    assert "ReleaseStore(repository, 'tbt-player-assets-v1'" in helper
    assert "player_profiles.json" in helper
