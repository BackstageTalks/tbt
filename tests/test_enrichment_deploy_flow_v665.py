from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_manual_player_enrichment_redeploys_site():
    text = read('.github/workflows/player-enrichment.yml')
    assert 'deploy:' in text
    assert 'needs: enrich' in text
    assert 'scripts/prepare_feed.py' in text
    assert 'scripts/verify_presentation_feed.py api/data/feed.json --summary' in text
    assert 'Azure/static-web-apps-deploy@v1' in text
    assert 'tbt-production-deploy' in text


def test_refresh_and_normal_deploy_validate_presentation_merge():
    for path in ('.github/workflows/data.yml', '.github/workflows/ci.yml'):
        text = read(path)
        assert 'scripts/verify_presentation_feed.py api/data/feed.json --summary' in text


def test_verifier_guards_completely_unenriched_current_feed_but_allows_optional_asset_outage():
    text = read('scripts/verify_presentation_feed.py')
    assert 'zero player presentation enrichment' in text
    assert 'player_assets metadata unavailable' in text
    assert 'local tournament-type fallbacks' in text
    assert 'no player_assets merge metadata' not in text
    assert 'no tournament_assets merge metadata' not in text


def test_player_enrichment_is_presentation_only_and_budgeted():
    text = read('.github/workflows/player-enrichment.yml')
    assert 'scripts/pipeline.py refresh' not in text
    assert 'RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}' in text
    assert 'group: tbt-history-data-writer' not in text
    assert 'scripts/plan_player_enrichment_budget.py' in text
    assert 'max_total_requests' in text


def test_presentation_guard_rejects_old_prediction_shape():
    text = read('scripts/verify_presentation_feed.py')
    assert 'no point-in-time recent_form data' in text
    assert 'rows contain no tournament IDs' in text


def test_match_intelligence_falls_back_to_serving_feed_after_live_failure():
    text = read('api/function_app.py')
    assert 'Match intelligence live enrichment failed' in text
    assert 'live_provider": False' in text
