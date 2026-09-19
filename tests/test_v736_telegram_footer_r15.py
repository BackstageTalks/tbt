from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'
APP=(WEB/'app.js').read_text(encoding='utf-8')
INDEX=(WEB/'index.html').read_text(encoding='utf-8')
CSS=(WEB/'blinq-app.css').read_text(encoding='utf-8')

def test_telegram_panel_has_json_and_admin_editor():
    cfg=json.loads((WEB/'config'/'telegram-groups.json').read_text(encoding='utf-8'))
    assert cfg['schema']==1 and isinstance(cfg['groups'],list)
    assert 'telegramGroupsPanel' in INDEX
    assert 'function renderTelegramGroupsPanel' in APP
    assert "['telegram','Telegram','Skupiny · odkazy']" in APP
    assert 'function renderAdminTelegram' in APP
    assert 'data-tg-group-field' in APP

def test_footer_watermark_is_visible_and_legacy_rail_is_removed():
    assert 'footer-watermark-logo' in INDEX
    assert 'width:126px!important' in CSS and 'opacity:.20!important' in CSS
    assert 'legacy-component-marker' not in INDEX
    assert 'Prémiové predikcie' not in INDEX

def test_r15_asset_cache_contract():
    assert 'content="736-r15"' in INDEX
    for asset in ('blinq-app.css','auth.js','responsive.js','app.js'):
        assert f'/{asset}?v=7360&p=15' in INDEX
