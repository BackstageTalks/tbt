from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_info_audience_presets_keep_live_elite_but_allow_general_info():
    app=(ROOT/'web/app.js').read_text();block=app.split('function renderAdminInsights(){',1)[1].split('function renderAdminSupport(){',1)[0]
    assert "['elite','legend','goat']" in block and 'insight-audience-elite' in block
    assert 'insight-audience-all' in block and 'insight-audience-rookie' in block
    assert 'LIVE upozornenia zostávajú iba ELITE+' in block

def test_bell_and_light_poll():
    app=(ROOT/'web/app.js').read_text();assert "['elite','legend','goat','admin']" in app
    block=app.split('function setupLiveRefresh(){',1)[1].split('function finishBootSplash',1)[0];assert 'setInterval(privateRefresh,30*1000)' in block

def test_server_timer():
    api=(ROOT/'api/function_app.py').read_text();assert '@app.timer_trigger' not in api and '_LIVE_RADAR_TTL_SECONDS = 45' in api and '_run_live_radar(force=False,publish=True)' in api
