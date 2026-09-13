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


def test_verifier_guards_completely_unenriched_current_feed():
    text = read('scripts/verify_presentation_feed.py')
    assert 'zero player presentation enrichment' in text
    assert 'no player_assets merge metadata' in text
    assert 'no tournament_assets merge metadata' in text
