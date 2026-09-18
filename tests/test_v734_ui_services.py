import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
AUTH = (ROOT / 'web' / 'auth.js').read_text(encoding='utf-8')
INDEX = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
CSS = (ROOT / 'web' / 'final-polish-734.css').read_text(encoding='utf-8')
UI = json.loads((ROOT / 'web' / 'ui-config.json').read_text(encoding='utf-8'))
SITE = json.loads((ROOT / 'web' / 'config' / 'site-content.json').read_text(encoding='utf-8'))


def test_v734_asset_revision_and_polish_loaded_last():
    assert UI['revision'] == '7.3.4'
    assert UI['asset_revision'] == 7340
    assert '/final-polish-734.css?v=7340' in INDEX
    assert INDEX.index('/final-polish-731.css') < INDEX.index('/final-polish-734.css')


def test_login_loader_and_footer_have_blinq_background_watermarks():
    assert "url('/assets/blinq_background.webp')" in CSS
    assert CSS.count("url('/assets/blinq_logo.svg')") >= 3
    assert 'bootEyebrow' in INDEX and 'bootStatus' in INDEX
    assert 'auth-copy h2' in CSS and 'font-size:18px' in CSS


def test_footer_status_is_freshness_aware_not_hardcoded_live():
    assert 'feedAgeMin' in APP and 'liveAgeMin' in APP
    assert "liveAgeMin<=3" in APP
    assert "footer.feed_stale" in APP
    assert "footer.live_ok" in APP


def test_helper_copy_is_json_backed():
    assert 'ui_copy' in UI
    assert 'loading' in UI['ui_copy'] and 'auth' in UI['ui_copy'] and 'footer' in UI['ui_copy']
    assert 'form_copy' in SITE['support']
    assert 'supportFormCopy()' in APP


def test_admin_exposes_support_system_and_all_info_audiences():
    assert "['support','Support','Požiadavky']" in APP
    assert "['system','Systém','Diagnostika']" in APP
    assert "['rookie','pro','elite','legend','goat'].filter" in APP


def test_live_radar_not_mislabelled_offline_when_only_history_storage_is_down():
    assert 'História upozornení je dočasne nedostupná. LIVE radar ďalej funguje.' in json.dumps(UI, ensure_ascii=False)
    assert "if(channel==='live')" in APP
    assert 'insight-storage-note' in CSS


def test_storage_errors_are_user_friendly():
    assert 'SUPPORT_STORAGE_UNAVAILABLE' in AUTH
    assert 'ADMIN_STORAGE_UNAVAILABLE' in AUTH

def test_admin_storage_reuses_unified_or_media_connection(monkeypatch):
    from tbt.services import admin_storage
    for key in ('BLINQ_ADMIN_STORAGE_CONNECTION_STRING','BLINQ_STORAGE_CONNECTION_STRING','BLINQ_MEDIA_STORAGE_CONNECTION_STRING','AzureWebJobsStorage'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('BLINQ_MEDIA_STORAGE_CONNECTION_STRING','UseDevelopmentStorage=true')
    value, source = admin_storage._connection_string_source()
    assert value == 'UseDevelopmentStorage=true'
    assert source == 'BLINQ_MEDIA_STORAGE_CONNECTION_STRING'
    monkeypatch.setenv('BLINQ_STORAGE_CONNECTION_STRING','DefaultEndpointsProtocol=https;AccountName=x;AccountKey=y')
    value, source = admin_storage._connection_string_source()
    assert source == 'BLINQ_STORAGE_CONNECTION_STRING'


def test_storage_diagnostics_explain_private_service_dependency():
    from tbt.services import admin_storage
    import inspect
    source = inspect.getsource(admin_storage.admin_storage_diagnostics)
    assert 'recommended_setting' in source
    assert 'premium_info' in source and 'live_alert_history' in source and 'support' in source
    assert 'INFO / LIVE / SUPPORT' in APP
    assert 'BLINQ_STORAGE_CONNECTION_STRING' in APP


def test_frontend_release_probe_and_no_cache_entry_document():
    release=json.loads((ROOT/'web'/'release.json').read_text(encoding='utf-8'))
    static=json.loads((ROOT/'web'/'staticwebapp.config.json').read_text(encoding='utf-8'))
    assert release['frontend_marker']=='blinq-web-734'
    assert 'data-web-release="7.3.4"' in INDEX
    for route in ('/','/index.html','/release.json'):
        rule=next(row for row in static['routes'] if row.get('route')==route)
        assert 'no-store' in rule['headers']['Cache-Control']


def test_stale_data_workflow_cannot_roll_back_frontend():
    data=(ROOT/'.github'/'workflows'/'data.yml').read_text(encoding='utf-8')
    player=(ROOT/'.github'/'workflows'/'player-enrichment.yml').read_text(encoding='utf-8')
    ci=(ROOT/'.github'/'workflows'/'ci.yml').read_text(encoding='utf-8')
    assert 'BLINQ_SKIP_STALE_DEPLOY=true' in data
    assert 'git rev-parse origin/main' in data
    assert 'ref: main' in player
    assert 'Verify deployed frontend release' in ci
    assert 'blinq-web-734' in ci
