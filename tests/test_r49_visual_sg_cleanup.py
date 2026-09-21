from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'blinq-app.css').read_text(encoding='utf-8')
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
SG = (ROOT / 'api' / 'tbt' / 'services' / 'sg_selection.py').read_text(encoding='utf-8')
DOUBLES = (ROOT / 'api' / 'tbt' / 'services' / 'doubles_selection.py').read_text(encoding='utf-8')
RELEASE = json.loads((ROOT / 'web' / 'release.json').read_text(encoding='utf-8'))
UI = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))


def test_r49_release_identity_and_cache_bust():
    assert RELEASE['patch'] == UI['ui_patch'] == '736-r53'
    assert 'content="736-r53"' in INDEX
    for asset in ('blinq-app.css', 'auth.js', 'responsive.js', 'app.js'):
        assert f'/{asset}?v=7360&p=53' in INDEX
    assert 'BlinQ runtime patch 7.3.6-r53' in CSS


def test_sets_are_total_match_sets_not_direction_probability():
    assert '"projection_unit": "sets"' in SG
    assert '"projection": round(expected_sets, 2)' in SG
    assert '"reference_projection": round(line, 2)' in SG
    assert 'sets-games-projection-v4' in SG
    assert 'if (expected_sets > line) != is_over:' in SG
    assert 'setsTotalProjectionValue' in APP
    assert "`${d.projection.toFixed(2)} Sets`" in APP


def test_results_only_expose_separate_sets_and_games_filters():
    visible_filter = "['all','top_daily','prime','value','ace','double_faults','sets','games','doubles']"
    assert visible_filter in APP
    assert "['all','top_daily','prime','value','ace','double_faults','sets','games','sg','doubles']" not in APP


def test_doubles_ev_is_analysis_only_not_publication_gate():
    assert 'MIN_DATA_DEPTH = 0.35' in DOUBLES
    assert 'MIN_PUBLIC_PROBABILITY = 0.58' in DOUBLES
    assert 'expected_value_filter' in DOUBLES
    assert 'analysis_only' in DOUBLES
    assert 'rejected["ev"]' not in DOUBLES
    assert 'MIN_EXPECTED_VALUE' not in DOUBLES


def test_one_bottom_right_watermark_and_no_footer_duplicate():
    assert '<i class="wm wm-b"></i>' in INDEX
    assert 'wm wm-a' not in INDEX and 'wm wm-c' not in INDEX
    assert '.anti-share-watermarks .wm-b' in CSS
    assert 'right:24px!important;bottom:20px!important' in CSS
    assert '.site-footer:before{display:none!important;content:none!important}' in CSS


def test_results_photo_fallback_and_admin_telegram_layout_are_explicit():
    assert "const p1Photo=playerPhotoSource(r,p1,'player1');" in APP
    assert "const p2Photo=playerPhotoSource(r,p2,'player2');" in APP
    assert 'admin-field-label-with-icon' in APP
    assert 'admin-field-label-with-icon' in CSS
    assert 'id="adminUserTelegram"' in APP
