from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_info_audience_presets_and_dynamic_live_rule():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert 'live_min_level' in app
    assert 'membershipLevelsFrom' in app
    assert 'insight-audience-preset' in app
    for label in ('VŠETCI','PRO+','ELITE+','LEGEND+','GOAT','LIVE PRAVIDLO'):
        assert label in app
    assert 'Ručné a automatické LIVE upozornenia zostávajú iba ELITE+' not in app

def test_bell_and_light_poll():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8');assert "['rookie','pro','elite','legend','goat','admin']" in app
    block=app.split('function setupLiveRefresh(){',1)[1].split('function finishBootSplash',1)[0];assert 'setInterval(privateRefresh,30*1000)' in block

def test_server_timer():
    api=(ROOT/'api/function_app.py').read_text(encoding='utf-8');assert '@app.timer_trigger' not in api and '_LIVE_RADAR_TTL_SECONDS = 45' in api and '_run_live_radar(force=False,publish=True)' in api


def test_info_audience_is_exact_per_message_while_live_keeps_global_minimum():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    storage=(ROOT/'api/tbt/services/admin_storage.py').read_text(encoding='utf-8')
    block=app.split('function syncAdminInsightAudienceForType',1)[1].split('function renderAdminInsights',1)[0]
    assert 'liveLevels=new Set(membershipLevelsFrom(cfg.live_min_level))' in block
    assert 'infoLevels=new Set(cfg.editable_levels||membershipHierarchy)' in block
    assert 'membershipLevelsFrom(cfg.info_min_level)' not in block
    assert 'INFO publikum sa riadi presne levelmi zvolenými pri tejto správe.' in block
    assert 'return list(_INSIGHT_LEVELS)' in storage


def test_admin_info_schedule_renders_utc_as_browser_local_datetime():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    block=app.split('function adminDatetimeValue',1)[1].split('function adminAudiencePresetLevels',1)[0]
    assert 'date.getFullYear()' in block
    assert 'date.getMonth()+1' in block
    assert 'date.getHours()' in block
    assert "replace('Z','')" not in block
    assert "new Date($('adminInsightFrom').value).toISOString()" in app

def test_new_info_defaults_to_local_end_of_day_without_overwriting_manual_edit():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    draft=app.split('function adminInsightDraft()',1)[1].split('function adminDatetimeValue',1)[0]
    assert "active_until:adminInsightEndOfDayIso()" in draft
    helper=app.split('function adminInsightEndOfDayIso',1)[1].split('function adminDatetimeValue',1)[0]
    assert 'date.setHours(23,59,0,0)' in helper
    assert 'data-info-auto="${item.id?\'0\':\'1\'}"' in app
    wire=app.split("const insightForm=$('adminInsightForm')",1)[1].split("if(insightForm)insightForm.onsubmit",1)[0]
    assert "fromInput.onchange=()=>syncAdminInsightDefaultExpiry(insightForm)" in wire
    assert "untilInput.dataset.infoAuto='0'" in wire
    assert "syncAdminInsightDefaultExpiry(insightForm)" in wire


def test_admin_info_batch_composer_publishes_up_to_five_separate_messages():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    assert 'adminInsightMessageHtml' in app
    assert 'data-admin-action="insight-message-add"' in app
    assert "if(count>=5)return" in app
    assert "Promise.allSettled(messages.map(row=>BlinqAuth.adminCreateInsight" in app
    assert "Naraz môžeš publikovať 1 až 5 správ." in app
    assert "SPOLOČNÉ NASTAVENIA" in app


def test_admin_info_manual_win_loss_void_history_contract():
    app=(ROOT/'web/app.js').read_text(encoding='utf-8')
    auth=(ROOT/'web/auth.js').read_text(encoding='utf-8')
    api=(ROOT/'api/function_app.py').read_text(encoding='utf-8')
    storage=(ROOT/'api/tbt/services/admin_storage.py').read_text(encoding='utf-8')
    for outcome in ('win','loss','void'):
        assert f"'{outcome}'" in app
    assert 'admin-info-results-columns' in app
    assert 'adminSettleInfoResult' in auth
    assert 'adminDeleteInfoResult' in auth
    assert 'route="v1/admin/info-results"' in api
    assert 'route="v1/admin/insights/{insight_id}/result"' in api
    assert 'def save_info_result' in storage
    assert 'def list_info_results' in storage
    assert 'Results are stored independently from the INFO row' in storage
