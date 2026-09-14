from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'web/index.html').read_text(encoding='utf-8')
APP = (ROOT / 'web/app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'web/redesign-678.css').read_text(encoding='utf-8')
BASE_CSS = (ROOT / 'web/blinq.css').read_text(encoding='utf-8')
UI = json.loads((ROOT / 'web/ui-config.json').read_text(encoding='utf-8'))
BACKEND = (ROOT / 'api/function_app.py').read_text(encoding='utf-8')


def test_release_678_and_active_redesign_asset():
    assert UI['ui_revision'] == '6.7.8'
    assert UI['revision'] == '6.7.8'
    assert 'RELEASE = "6.7.8"' in BACKEND
    assert '/redesign-678.css?v=678' in INDEX
    for asset in ('blinq.css', 'auth.js', 'responsive.js', 'app.js'):
        assert f'/{asset}?v=678' in INDEX


def test_reference_header_has_no_visible_search_and_keeps_private_feed_bell():
    header = INDEX.split('<header class="site-header dashboard-topbar reference-topbar">',1)[1].split('</header>',1)[0]
    assert 'headerSearchInput' not in header
    assert 'searchInput' not in header
    assert 'notificationButton' in header
    assert 'notificationBadge' in header
    assert 'notification-bell-icon' in header
    assert 'communityNavButton' in header
    assert 'reference-nav' in header


def test_search_runtime_hooks_are_non_visual_only():
    assert '<div class="runtime-hooks" aria-hidden="true">' in INDEX
    hooks = INDEX.split('<div class="runtime-hooks" aria-hidden="true">',1)[1].split('</div>\n  </div>',1)[0]
    assert 'id="searchInput"' in hooks
    assert 'id="headerSearchInput"' in hooks


def test_reference_geometry_contract_is_encoded():
    for expected in (
        'height:68px!important',
        'height:196px!important',
        'grid-template-columns:minmax(0,1fr) 292px!important',
        'height:51px!important',
        'min-height:54px!important',
    ):
        assert expected in CSS
    assert 'body#blinqPremium.blinq-home .site-footer{display:none!important}' in CSS
    assert 'body#blinqPremium .daily-tabs-row{min-height:48px!important;height:48px!important' in CSS


def test_reference_hero_uses_current_blinq_branding_and_new_asset():
    hero = UI['elements']['HERO_BANNER_1']['content']
    assert hero['image_url'] == '/assets/hero-reference-v678.webp'
    assert hero['headline'] == 'Tennis intelligence'
    assert hero['accent_text'] == 'for a smarter tomorrow.'
    assert hero['eyebrow'] == 'DÁTA. KONTEXT. LEPŠIE ROZHODNUTIA.'
    assert (ROOT/'web/assets/hero-reference-v678.webp').exists()
    assert INDEX.count('/assets/blinq_logo.svg') >= 2


def test_daily_dashboard_keeps_agreed_tabs_and_reference_table_columns():
    tabs = UI['dashboard']['daily_hub']['tabs']
    assert tabs['daily']['label'] == 'Prehľad'
    assert tabs['top']['label'] == 'TOP'
    assert tabs['value']['label'] == 'Value'
    assert "`<button type=\"button\" class=\"daily-hub-tab daily-hub-results\"" in APP
    assert "return ['ČAS','TURNAJ','ZÁPAS','PREDIKCIA','KURZ','BLINQ %','EDGE','DETAIL']" in APP
    assert 'Zobraziť celú ponuku' in APP
    assert "showUpgradePrompt('elite'" in APP


def test_match_detail_is_inline_right_rail_on_predictions_route():
    assert 'id="dashboardRightRail"' in INDEX
    assert 'id="dashboardSidebarDefault"' in INDEX
    assert 'id="dashboardMatchDetail"' in INDEX
    branch = APP.split("function openMatch(m,tab='daily'",1)[1].split('const signalRows=',1)[0]
    assert "state.route==='predictions'&&$('dashboardMatchDetail')" in branch
    assert 'state.activeSidebarMatch={row,tab}' in branch
    assert 'renderDashboardSidebar();renderDailyHub();' in branch
    assert 'return;' in branch
    assert "dialog.showModal()" not in branch
    assert 'body#blinqPremium.blinq-home #matchDialog{display:none!important}' in CSS


def test_inline_match_detail_has_four_requested_tabs_and_close_back_to_sidebar():
    detail = APP.split('function renderSidebarMatchDetail',1)[1].split('function renderDashboardSidebar',1)[0]
    for tab in ('Prehľad','Štatistiky','Radar','História'):
        assert tab in detail
    assert 'data-sidebar-close' in detail
    assert 'state.activeSidebarMatch=null' in detail
    assert 'renderRadarComparison(row)' in detail
    assert 'renderMatchStatsPanel(row)' in detail
    assert 'renderMatchHistoryPanel(row)' in detail


def test_private_feed_defaults_to_elite_plus_but_message_audience_is_editable():
    cfg = UI['notifications']
    assert cfg['enabled'] is True
    assert cfg['default_levels'] == ['elite','legend','goat']
    assert cfg['messages'] == []
    assert 'data-message-level' in APP
    assert 'accessContexts.filter' in APP
    assert "levels.includes(plan)" in APP
    assert 'adminMessageForm' in APP
    assert 'adminMessageBody' in APP
    assert 'adminMessageExpiry' in APP
    assert 'adminMessageLink' in APP
    assert 'adminMessagePinned' in APP


def test_private_feed_is_one_way_admin_publish_and_user_read_tracking():
    assert 'function notificationReadIds()' in APP
    assert 'function markNotificationsRead(ids)' in APP
    assert 'function visibleNotifications()' in APP
    assert 'function renderNotifications()' in APP
    assert 'publishUiConfig()' in APP
    assert "data-admin-action=\"delete-message\"" in APP
    assert 'notification-item' in CSS
    assert 'admin-chat-composer' in CSS
    # No user-reply composer exists in the public notification panel.
    panel = INDEX.split('id="notificationPanel"',1)[1].split('</aside>',1)[0]
    assert '<textarea' not in panel
    assert '<input' not in panel


def test_vip_footer_matches_reference_structure_with_four_benefits_and_current_logo():
    vip = UI['elements']['VIP_RAIL']['content']
    for n in range(1,5):
        assert vip[f'benefit_{n}_title']
        assert vip[f'benefit_{n}_text']
    assert 'const benefits=[1,2,3,4].map' in APP
    assert 'grid-template-columns:repeat(4,minmax(0,1fr))!important' in CSS
    assert "background:url('/assets/blinq_logo.svg')" in CSS


def test_public_active_config_has_no_tipy_bety_wording():
    text = json.dumps(UI, ensure_ascii=False) + INDEX
    assert not re.search(r'\b(?:tipy|bety)\b', text, flags=re.I)


def test_old_header_feature_slots_are_not_visible_in_reference_header():
    assert 'body#blinqPremium .reference-topbar #headerFeatureStrip{display:none!important}' in CSS
    header_cta = UI.get('header_cta',{})
    assert header_cta.get('enabled') is False
    assert int(header_cta.get('slot_count',0)) == 0
