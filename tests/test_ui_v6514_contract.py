import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_v6514_admin_cleanup_and_clean_avatar_assets():
    cfg=json.loads((ROOT/'web'/'ui-config.json').read_text(encoding='utf-8'))
    assert tuple(map(int,cfg['ui_revision'].split('.'))) >= (6,5,14)
    assert cfg['rss']['enabled'] is False
    assert cfg['rss']['sources'] == []
    assert cfg['ad_fallbacks']['rss_enabled'] is False
    assert 'rss_news' not in cfg['ad_fallbacks']['priority']
    for plan in ('rookie','pro','elite','legend','goat'):
        entry=cfg['assets']['account_avatars'][plan]
        for key,value in entry.items():
            if key in ('m','w','default','marketing'):
                assert 'v6514' in value
                assert (ROOT/'web'/value.lstrip('/')).exists()

def test_v6514_admin_tabs_explain_advanced_tools_and_drop_rss():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    assert "['performance','Model Quality'" in app
    assert "['campaigns','Banner campaigns'" in app
    tabs=app.split('function renderAdminRoute()',1)[1].split('function rerenderAdmin',1)[0]
    assert 'RSS feeds' not in tabs
    assert "state.adminTab==='feeds'" not in tabs
    assert 'Banner campaigns · optional' in app
    assert 'live settled accuracy, holdout metrics and historical backtests' in app

def test_v6514_avatar_labels_are_never_rendered_on_artwork():
    app=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    fn=app.split('function planAvatarHtml',1)[1].split('function renderPlanCardsForAccount',1)[0]
    assert '<em>' not in fn
    assert 'marketingAvatarUrl(style)' in fn
    assert '?v=v6514' in app
