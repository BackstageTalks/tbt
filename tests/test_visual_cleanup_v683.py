from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "polish-683.css").read_text(encoding="utf-8")


def test_v683_polish_layer_is_loaded_after_v681():
    cfg = json.loads((ROOT / 'web/ui-config.json').read_text(encoding='utf-8'))
    cache = cfg['asset_revision']
    p681 = f'/polish-681.css?v={cache}'
    p683 = f'/polish-683.css?v={cache}'
    assert p683 in HTML
    assert HTML.index(p681) < HTML.index(p683)


def test_close_controls_use_svg_not_platform_multiplication_glyph():
    for control_id in ('accountDialogClose', 'dialogClose', 'upgradeDialogClose', 'insightDrawerClose'):
        fragment = HTML.split(f'id="{control_id}"', 1)[1].split('</button>', 1)[0]
        assert '<svg' in fragment
        assert '×' not in fragment
    assert '.dialog-close svg' in CSS


def test_mobile_search_is_explicitly_reset_from_native_browser_skin():
    assert '.reference-search>input[type="search"]' in CSS
    assert 'appearance:none!important' in CSS
    assert 'background:transparent!important' in CSS


def test_private_feed_elite_subtitle_is_not_visible():
    assert 'id="insightAudienceLabel" hidden' in HTML


def test_expand_control_uses_svg_icons():
    render = APP.split("function renderDailyHub(){", 1)[1].split("function marketPreviewCard", 1)[0]
    assert 'expand.innerHTML=' in render
    assert '<svg viewBox=' in render


def test_daily_hub_clicks_are_not_swallowed_by_board_mode_host_attribute():
    wire = APP.split('function wireDailyHub(){', 1)[1].split('function setRoute(', 1)[0]
    assert "target.closest('button[data-board-mode]')" in wire
    assert "target.closest('[data-board-mode]')" not in wire


def test_private_feed_match_cta_reopens_full_match_detail():
    assert "openMatch(normalize(found.row),found.tab,found.row)" in APP


def test_match_popout_inherits_final_polish_layer():
    popout = APP.split('function openMatchPopout(){', 1)[1].split('function openMatch(', 1)[0]
    assert '/polish-683.css?v=6864' in popout
    assert '/polish-684.css?v=6864' in popout
    assert '/polish-685.css?v=6864' in popout


def test_admin_delete_icon_buttons_use_svg_close_icons():
    assert 'title="Odstrániť inzerenta"><svg' in APP
    assert 'data-admin-action="delete-rss-source"' in APP
    rss = APP.split('data-admin-action="delete-rss-source"', 1)[1].split('</button>', 1)[0]
    assert '<svg' in rss
