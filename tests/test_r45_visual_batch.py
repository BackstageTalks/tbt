from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'blinq-app.css').read_text(encoding='utf-8')
UI = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
RELEASE = json.loads((ROOT / 'web' / 'release.json').read_text(encoding='utf-8'))
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')


def test_r45_release_identity_and_cache_bust():
    assert RELEASE['patch'] == UI['ui_patch'] == '736-r52'
    assert 'content="736-r52"' in INDEX
    for asset in ('blinq-app.css', 'auth.js', 'responsive.js', 'app.js'):
        assert f'/{asset}?v=7360&p=52' in INDEX


def test_r45_time_cells_show_compact_date_under_time():
    assert 'const fmtCompactDate = value =>' in APP
    assert "return `${get('day')}.${get('month')}.${get('year')}`;" in APP
    assert 'timeDateHtml(scheduled)' in APP
    assert "timeDateHtml(row?.scheduled_at||row?.date,'card-time-stack')" in APP
    assert "timeDateHtml(m.date,'card-time-stack')" in APP
    assert '.hub-time-stack' in CSS and '.card-time-stack' in CSS


def test_r45_short_odds_and_aces_labels_are_clean():
    assert "prime:'SHORT ODDS'" in APP
    assert "ace:'ACES'" in APP
    assert UI['dashboard']['daily_hub']['tabs']['ace']['label'] == 'ACES'
    assert "?lcopy('Double Faults','Dvojchyby','Dvojchyby'):'Aces'" in APP
    assert '${escapeHtml(d.market.toUpperCase())} · ' in APP


def test_r45_projection_cards_expose_direction_and_line():
    assert 'function projectionDirectionLabel(row)' in APP
    assert 'function projectionReferenceLine(row,sourceTab=' in APP
    assert 'function projectionPickText(row,sourceTab=' in APP
    assert "if(market==='games')" in APP
    assert "if(market==='ace'||market==='double_faults'||market==='aces')" in APP
    assert "pick=projectionPickText(row,sourceTab)" in APP
    assert "pick=projectionPickText(row,projectionTab)" in APP
    assert "selection:projectionPickText(row,market)" in APP


def test_r45_player_photo_resolution_uses_repo_fallback_pipeline_everywhere():
    assert 'function playerPhotoSource(row,player,side=' in APP
    assert 'player?.photo_url,player?.image_url,player?.photo,player?.headshot_url,player?.avatar_url' in APP
    assert "p1Photo:playerPhotoSource(row,player1,'player1')" in APP
    assert "const p1Photo=playerPhotoSource(row,p1,'player1'),p2Photo=playerPhotoSource(row,p2,'player2');" in APP
    assert '/assets/missing_foto_m.webp' in APP
    assert '/assets/missing_foto_w.webp' in APP


def test_r45_rating_readability_is_larger_without_changing_access_logic():
    assert 'prediction-card visual/data clarity batch' in CSS
    assert '.daily-hub-table .hub-confidence strong' in CSS
    assert 'font-size:13.5px!important' in CSS
    assert '.market-card .pick-score .probability' in CSS
    assert "if(tab==='doubles')return marketRows('doubles').filter(offerSurfaceEligible);" in APP
