from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web/app.js').read_text(encoding='utf-8')
INDEX=(ROOT/'web/index.html').read_text(encoding='utf-8')
CSS=(ROOT/'web/blinq.css').read_text(encoding='utf-8')
UI=json.loads((ROOT/'web/ui-config.json').read_text(encoding='utf-8'))


def test_loading_is_half_size_and_ball_is_animated_layer():
    assert 'boot-tennis-ball' in INDEX
    assert 'width:min(280px,72vw)!important' in CSS
    assert '@keyframes blinqBallPingPong' in CSS


def test_preview_tab_is_removed_from_daily_hub():
    assert "calendar:'Preview'" not in APP
    render=APP.split('function renderDailyHub(){',1)[1].split('function marketPreviewCard',1)[0]
    assert "['daily','top','value','ace','games','doubles','board']" in render


def test_value_priority_top_under_150_daily_from_150():
    assert 'function valuePickIds()' in APP
    assert "!valueIds.has(dailyPickIdentity(row))&&Number.isFinite(odds)&&odds>=1.50" in APP
    assert "!valueIds.has(dailyPickIdentity(row))&&Number.isFinite(odds)&&odds>=1.25&&odds<1.50" in APP


def test_results_have_24h_and_void_contract():
    assert "['1',publicText('24 hours')]" in APP
    assert 'function publicationOutcome(publication)' in APP
    assert "kind:'void'" in APP
    assert '○ VOID' in APP
    assert "outcome.kind==='void'?'0.00u'" in APP


def test_player_flags_and_tournament_fallback_assets():
    assert 'flagEmoji' in APP and 'hub-flag' in APP
    assert 'player1_country_code' in APP and 'player2_country_code' in APP
    fallbacks=ROOT/'web/assets/tournament-fallbacks'
    expected=['challenger.svg','itf.svg','atp.svg','wta.svg','us-open.svg','wimbledon.svg','roland-garros.svg','australian-open.svg','masters-1000.svg']
    for name in expected:
        assert (fallbacks/name).is_file(), name
    assert '/assets/tournament-fallbacks/challenger.svg' in APP
    assert '/assets/tournament-fallbacks/us-open.svg' in APP


def test_bottom_link_rail_has_no_brand_logo_and_is_admin_configurable():
    fn=APP[APP.index('function renderVipRail'):APP.index('function renderFooterConfig')]
    assert 'vip-brand-logo' not in fn
    assert 'vip-link-card' in fn
    assert 'benefit_${n}_title_size' in APP
    assert 'benefit_${n}_text_size' in APP
    assert 'benefit_${n}_icon_url' in APP
    assert 'benefit_${n}_link' in APP
    content=UI['elements']['VIP_RAIL']['content']
    # Legacy config may still carry brand_logo, but the public renderer must ignore it.
    assert 'vip-brand-logo' not in fn
    for n in range(1,5):
        assert content[f'benefit_{n}_title_size'] == 14
        assert content[f'benefit_{n}_text_size'] == 11
        assert f'benefit_{n}_link' in content
