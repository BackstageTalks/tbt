import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
AUTH = (ROOT / 'web' / 'auth.js').read_text(encoding='utf-8')
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'blinq-app.css').read_text(encoding='utf-8')
API = (ROOT / 'api' / 'function_app.py').read_text(encoding='utf-8')
ADMIN_STORAGE = (ROOT / 'api' / 'tbt' / 'services' / 'admin_storage.py').read_text(encoding='utf-8')
DOUBLES = (ROOT / 'api' / 'tbt' / 'services' / 'doubles_selection.py').read_text(encoding='utf-8')
WORKFLOW = (ROOT / '.github' / 'workflows' / 'data.yml').read_text(encoding='utf-8')


def test_r46_release_and_cache_contract():
    release = json.loads((ROOT / 'web' / 'release.json').read_text(encoding='utf-8'))
    ui = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
    assert release['patch'] == ui['ui_patch'] == '736-r53'
    assert 'content="736-r53"' in INDEX
    for asset in ('blinq-app.css', 'auth.js', 'responsive.js', 'app.js'):
        assert f'/{asset}?v=7360&p=53' in INDEX
    assert "const AUTH_RUNTIME = '736-r53'" in AUTH


def test_rookie_stays_internal_but_public_membership_is_free():
    tiers = json.loads((ROOT / 'web' / 'config' / 'membership-tiers.json').read_text(encoding='utf-8'))['tiers']
    assert tiers['rookie']['label'] == 'BlinQ ROOKIE'
    assert tiers['rookie']['card_title'] == 'FREE'
    assert "if(id==='rookie')return 'FREE'" in APP
    assert "id==='rookie'&&status==='expired'" in APP
    assert 'data-reactivate-free' in APP
    assert 'route="v1/auth/free"' in API
    assert 'free_reactivation_requires_expired_account' in API
    assert '"plan": "rookie", "status": "active", "expires_at": None' in API


def test_account_cards_use_detail_description_and_membership_card_keeps_note_heading():
    # Account cards must use Admin -> Detailny popis, never the internal note fallback.
    assert "detail=String(p.description||'').trim()" in APP
    assert 'p.description||p.note' not in APP
    # Large upgrade/membership cards intentionally keep internal note as the heading above benefits.
    assert "featureHeading=String(p?.note||'').trim()" in APP
    assert 'upgrade-feature-heading' in APP


def test_info_all_really_includes_rookie_but_live_remains_gated():
    assert "if(preset==='all'||preset==='rookie+')return [...membershipHierarchy]" in APP
    assert "node.disabled=live?!liveLevels.has(node.value):false" in APP
    assert 'INFO publikum určuješ pri každej správe samostatne' in APP
    assert 'return list(_INSIGHT_LEVELS)' in ADMIN_STORAGE
    assert 'if insight_type in {"alert", "live_watch", "set2"}' in ADMIN_STORAGE


def test_results_projection_copy_is_not_duplicated():
    assert 'function projectionResultSelectionText' in APP
    assert 'projection_direction' in APP and 'reference_projection' in APP
    assert 'High\\s+Total\\s+Games' in APP
    # Type tag and pick remain separate; old scope + metric label was removed from formatter.
    formatter = APP.split('function projectionResultTypeLabel', 1)[1].split('function projectionResultSelectionText', 1)[0]
    assert 'SPOLU ZÁPAS' not in formatter


def test_login_family_background_and_single_corner_watermark_are_shared():
    assert '/assets/blinq_page_background.webp' in CSS
    assert 'anti-share-watermarks' in INDEX
    assert 'wm-b' in INDEX
    assert 'wm-a' not in INDEX and 'wm-c' not in INDEX
    assert '.boot-splash.boot-splash-tennis' in CSS
    assert '.blinq-admin .anti-share-watermarks' in CSS


def test_set2_is_a_real_conditional_live_feature():
    assert "state.liveRadarTab==='set2'" in APP
    assert 'live_second_set_projection' in (ROOT / 'api' / 'tbt' / 'services' / 'comeback_projection.py').read_text(encoding='utf-8')
    live = (ROOT / 'api' / 'tbt' / 'services' / 'live_comeback.py').read_text(encoding='utf-8')
    assert 'def set2_push_eligible' in live
    assert 'second_set_odds' in live
    assert 'kvalifikovaný kandidát pre 2. set' in APP


def test_doubles_pipeline_has_activation_and_fail_closed_gates():
    for literal in (
        'MIN_HISTORY_MATCHES = 200',
        'MIN_PAIR_MATCHES = 3',
        'MIN_MEMBER_MATCHES = 4',
        'MIN_DATA_DEPTH = 0.35',
        'MIN_PUBLIC_PROBABILITY = 0.58',
    ):
        assert literal in DOUBLES
    assert 'member_identity_coverage' in DOUBLES and '>= 0.90' in DOUBLES
    assert 'no_match_winner_odds' in DOUBLES
    assert 'expected_value_filter' in DOUBLES and 'analysis_only' in DOUBLES
    assert 'rejected["ev"]' not in DOUBLES
    assert 'doubles-data' in WORKFLOW
    assert 'enrich_doubles_history.py' in WORKFLOW
    assert '--doubles-odds-max-events' in WORKFLOW
