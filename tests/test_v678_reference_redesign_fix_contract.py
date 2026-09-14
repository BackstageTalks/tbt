from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
INDEX=(ROOT/'web/index.html').read_text(encoding='utf-8')
APP=(ROOT/'web/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'web/redesign-678.css').read_text(encoding='utf-8')
BACKEND=(ROOT/'api/function_app.py').read_text(encoding='utf-8')
UI=json.loads((ROOT/'web/ui-config.json').read_text(encoding='utf-8'))

def test_release_678_and_active_redesign_asset():
    assert UI['ui_revision']=='6.7.8'
    assert UI['revision']=='6.7.8'
    assert 'RELEASE = "6.7.8"' in BACKEND
    assert '/redesign-678.css?v=678' in INDEX
    assert (ROOT/'web/redesign-678.css').exists()

def test_reference_header_has_no_visible_search_and_keeps_private_feed_bell():
    header=INDEX.split('<header class="site-header dashboard-topbar reference-topbar">',1)[1].split('</header>',1)[0]
    assert 'id="insightBell"' in header
    assert 'type="search"' not in header
    assert 'headerSearchInput' not in header
    assert 'Predikcie' in header and 'Štatistiky' in header and 'Modely' in header and 'Komunita' in header and 'BlinQ VIP' in header

def test_reference_hero_uses_current_blinq_branding_and_new_asset():
    hero=UI['elements']['HERO_BANNER_1']['content']
    assert hero['image_url']=='/assets/hero-reference-v678.webp'
    assert (ROOT/'web/assets/hero-reference-v678.webp').exists()
    assert '/assets/blinq_logo.svg' in INDEX
    assert hero['eyebrow']=='DÁTA. KONTEXT. LEPŠIE ROZHODNUTIA.'
    assert hero['headline']=='Tennis intelligence'
    assert hero['accent_text']=='for a smarter tomorrow.'

def test_daily_dashboard_keeps_agreed_tabs_and_reference_table_columns():
    tabs=UI['dashboard']['daily_hub']['tabs']
    assert tabs['daily']['label']=='Prehľad'
    assert tabs['top']['label']=='TOP'
    assert tabs['value']['label']=='Value'
    assert '`<button type="button" class="daily-hub-tab daily-hub-results"' in APP
    assert "return ['ČAS','TURNAJ','ZÁPAS','PREDIKCIA','KURZ','BLINQ %','EDGE','DETAIL']" in APP

def test_match_detail_is_inline_right_rail_on_predictions_route():
    assert 'id="dashboardRightRail"' in INDEX
    assert 'id="dashboardSidebarDefault"' in INDEX
    assert 'id="dashboardSidebarMatch"' in INDEX
    assert 'id="matchDialog"' in INDEX  # compatibility hook may remain, daily detail must not use it
    wire=APP.split('function wireDailyHub(){',1)[1].split('function setRoute',1)[0]
    assert 'selectMatchInRail(current,state.dailyHubTab)' in wire
    assert 'openMatch(current' not in wire

def test_inline_match_detail_has_four_requested_tabs_and_close_back_to_sidebar():
    detail=APP.split('function renderSidebarMatchDetail',1)[1].split('function renderDashboardSidebar',1)[0]
    for label in ('Prehľad','Štatistiky','Radar','História'):
        assert label in detail
    assert 'data-rail-close-match' in detail
    assert 'renderMotivationPanel(row)' in detail

def test_private_feed_defaults_to_elite_plus_but_message_audience_is_editable():
    cfg=UI['notifications']
    assert cfg['enabled'] is True
    assert cfg['default_min_level']=='elite'
    assert cfg['default_levels']==['elite','legend','goat']
    assert cfg['editable_levels']==['rookie','pro','elite','legend','goat']
    assert cfg['one_way'] is True
    assert cfg['allow_user_replies'] is False

def test_private_feed_is_one_way_admin_publish_and_user_read_tracking():
    assert 'function notificationReadIds()' in APP
    assert 'function markInsightRead(id)' in APP
    assert 'BlinqAuth.markInsightRead(id)' in APP
    assert 'function renderAdminInsights()' in APP
    assert 'BlinqAuth.adminCreateInsight(payload)' in APP

def test_vip_footer_matches_reference_structure_with_four_benefits_and_current_logo():
    vip=UI['elements']['VIP_RAIL']['content']
    for n in range(1,5):
        assert vip[f'benefit_{n}_title']
        assert vip[f'benefit_{n}_text']
    assert vip['brand_logo']=='/assets/blinq_logo.svg'
    assert 'const benefits=[1,2,3,4]' in APP

def test_old_header_feature_slots_are_not_visible_in_reference_header():
    assert 'body#blinqPremium .reference-topbar #headerFeatureStrip{display:none!important}' in CSS
    header_cta=UI.get('header_cta',{})
    assert header_cta.get('enabled') is False
    assert int(header_cta.get('slot_count',0))==0

def test_reference_layout_is_wide_without_horizontal_table_scroll():
    assert '1900px' in CSS
    assert 'overflow-x:hidden!important' in CSS
    assert 'grid-template-columns:minmax(0,1fr) 360px!important' in CSS
