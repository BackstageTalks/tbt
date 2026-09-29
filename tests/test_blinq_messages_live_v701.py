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
