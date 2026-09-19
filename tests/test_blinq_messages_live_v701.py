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
