import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
API = (ROOT / 'api' / 'function_app.py').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'blinq-app.css').read_text(encoding='utf-8')
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')


def test_r47_release_contract():
    release = json.loads((ROOT / 'web' / 'release.json').read_text(encoding='utf-8'))
    ui = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    assert release['patch'] == ui['ui_patch'] == '736-r49'
    assert 'content="736-r49"' in INDEX
    assert 'BlinQ runtime patch 7.3.6-r49' in CSS
    for asset in ('blinq-app.css', 'auth.js', 'responsive.js', 'app.js'):
        assert f'/{asset}?v=7360&p=49' in INDEX


def test_projection_results_are_human_readable_and_projection_only_categories_share_clean_layout():
    assert 'function projectionResultSelectionText' in APP
    assert 'function projectionResultProjectionText' in APP
    assert 'function projectionResultActualText' in APP
    assert "const projectionOnly=['ace','double_faults','sg','sets','games'].includes(category)" in APP
    assert "projectionCategory=['ace','double_faults','sg','sets','games'].includes(category)" in APP
    assert "High\\s+Total\\s+Games" in APP
    assert "projectionResultNumber(opponent,publication,1)" in APP


def test_set2_public_diagnostics_are_exposed_without_inventing_market_data():
    assert 'set2_push_eligible, set2_push_thresholds' in API
    for key in ('"set2_candidates"', '"set2_priced"', '"set2_eligible"', '"set2_push_thresholds"'):
        assert key in API
    assert 'second_set_odds' in API
    assert 'liveRadarSet2Stats' in APP
    assert 'set2-summary' in APP


def test_admin_live_radar_uses_canonical_prime_keys_and_shows_set2_health():
    assert 'radar.prime_eligible??radar.eligible_prime_pool' in APP
    assert 'radar.prime_total??radar.prime_pool' in APP
    assert '2. set LIVE kurz' in APP
    assert 'adminSet2.eligible' in APP


def test_shared_background_watermarks_and_free_membership_contract_survive_r47():
    assert '/assets/blinq_page_background.webp' in CSS
    assert 'anti-share-watermarks' in INDEX
    assert 'wm-b' in INDEX
    assert 'wm-a' not in INDEX and 'wm-c' not in INDEX
    assert "if(id==='rookie')return 'FREE'" in APP
    assert 'data-reactivate-free' in APP
    assert "detail=String(p.description||'').trim()" in APP
