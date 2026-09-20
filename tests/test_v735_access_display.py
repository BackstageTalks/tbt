import json
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config
from tbt.services.entitlements import filter_feed_for_access

ROOT=Path(__file__).resolve().parents[1]
UI=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
APP=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
INDEX=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
CSS735=(ROOT/'web'/'blinq-app.css').read_text(encoding='utf-8')
CSS736=(ROOT/'web'/'blinq-app.css').read_text(encoding='utf-8')
CSS=CSS735+'\n'+CSS736
FUNCTION=(ROOT/'api'/'function_app.py').read_text(encoding='utf-8')
SITE=json.loads((ROOT/'web'/'config'/'site-content.json').read_text(encoding='utf-8'))


def _row(i):
    return {
        'event_id': f'e{i}', 'pick': f'P{i}', 'odds': 1.8,
        'player1': {'id': f'a{i}', 'name': f'A{i}', 'probability': .7},
        'player2': {'id': f'b{i}', 'name': f'B{i}', 'probability': .3},
        'scheduled_at': f'2026-09-19T{10+i%10:02d}:00:00Z',
    }


def _feed(n=12):
    rows=[_row(i) for i in range(n)]
    return {'top_daily_picks': rows, 'value_picks': [], 'ace_picks': [], 'doubles_picks': [], 'sg_picks': [], 'prime_picks': [], 'upcoming': rows, 'results': []}


def test_v735_runtime_config_validates_and_rookie_is_two_stable_random():
    validate_ui_config(UI)
    rule=UI['dashboard']['daily_hub']['tabs']['daily']['plans']['rookie']
    assert rule['visible_rows']==2
    assert rule['selection_mode']=='stable_random'
    assert rule['display_state']=='active'
    assert UI['dashboard']['daily_hub']['tabs']['value']['plans']['rookie']['visible_rows']==0
    assert UI['dashboard']['daily_hub']['tabs']['ace']['plans']['rookie']['visible_rows']==0


def test_stable_random_does_not_change_on_refresh_for_same_account():
    access={'status':'active','plan':'rookie','id':'user-1'}
    a,_=filter_feed_for_access(_feed(),access,UI)
    b,_=filter_feed_for_access(_feed(),access,UI)
    assert [r['event_id'] for r in a['top_daily_picks']]==[r['event_id'] for r in b['top_daily_picks']]
    assert len(a['top_daily_picks'])==2


def test_blurred_row_override_withholds_actual_pick_from_browser_payload():
    cfg=json.loads(json.dumps(UI))
    rule=cfg['dashboard']['daily_hub']['tabs']['daily']['plans']['rookie']
    rule['visible_rows']=2
    rule['selection_mode']='first'
    rule['row_overrides']={'2':'blurred'}
    data,manifest=filter_feed_for_access(_feed(),{'status':'active','plan':'rookie','id':'u'},cfg)
    # top_daily is governed by the same Daily/rookie rule server-side.
    assert len(data['top_daily_picks'])==1
    assert manifest['sections']['top_daily']['slot_states'][:2]==['active','blurred']
    assert manifest['sections']['top_daily']['slot_states'][2:]==['blurred']*10


def test_admin_has_real_display_route_and_show_blur_hide_controls():
    assert "['layout','Zobrazenie','Panely · riadky']" in APP
    assert 'accounts:renderAdminAccounts' in APP and 'layout:renderAdminLayout' in APP
    assert 'data-admin-hub-row-state' in APP
    assert 'data-simple-banner-state' not in APP
    assert 'data-banner-state-plan' not in APP
    assert 'Viditeľnosť podľa levelu' not in APP
    assert 'NÁHODNÉ / DEŇ' in APP


def test_upgrade_auth_footer_and_copy_are_v735_native():
    assert 'upgrade-requires-pill' in APP and 'upgrade-plan-grid' in APP
    assert 'upgrade-dialog-title' in CSS
    assert 'id="footerSystemStatus"' in INDEX
    assert 'Aktualizácia modelu: —' in INDEX
    assert 'auth-copy p,#authSubtitle' in CSS
    assert 'site-footer:before' in CSS
    assert 'ui_copy' in SITE and 'upgrade' in SITE['ui_copy']



def test_rookie_manifest_marks_remaining_offer_as_blurred_without_sending_rows():
    data,manifest=filter_feed_for_access(_feed(),{'status':'active','plan':'rookie','id':'rookie-blur'},UI)
    daily=manifest['sections']['daily']
    assert len(data['daily_picks'])==2
    assert len(daily['slot_states'])==12
    assert daily['slot_states'].count('active')==2
    assert daily['slot_states'].count('blurred')==10


def test_admin_can_force_a_later_row_visible_without_exposing_other_blurred_rows():
    cfg=json.loads(json.dumps(UI))
    rule=cfg['dashboard']['daily_hub']['tabs']['daily']['plans']['rookie']
    rule['visible_rows']=2
    rule['selection_mode']='first'
    rule['row_overrides']={'2':'hidden','5':'active','6':'blurred'}
    data,manifest=filter_feed_for_access(_feed(),{'status':'active','plan':'rookie','id':'row-override'},cfg)
    assert [row['event_id'] for row in data['daily_picks']]==['e0','e2']
    assert manifest['sections']['daily']['slot_states'][:6]==['active','hidden','blurred','blurred','active','blurred']


def test_games_and_sets_are_independent_admin_panels():
    cfg=json.loads(json.dumps(UI))
    sg=[]
    for i in range(8):
        row=_row(i)
        row['market']='games' if i<4 else 'sets'
        sg.append(row)
    payload=_feed(0); payload['sg_picks']=sg; payload['upcoming']=sg
    cfg['dashboard']['daily_hub']['tabs']['games']['plans']['rookie'].update({'visible_rows':1,'display_state':'active','blur_remaining':True})
    cfg['dashboard']['daily_hub']['tabs']['sets']['plans']['rookie'].update({'visible_rows':0,'display_state':'blurred','blur_remaining':True})
    data,manifest=filter_feed_for_access(payload,{'status':'active','plan':'rookie','id':'market-panels'},cfg)
    assert [r['market'] for r in data['sg_picks']]==['games']
    assert manifest['sections']['games']['returned']==1
    assert manifest['sections']['sets']['returned']==0
    assert manifest['sections']['sets']['display_state']=='blurred'
