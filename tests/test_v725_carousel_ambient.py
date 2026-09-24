from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
BANNERS = json.loads((WEB / "config" / "banners.json").read_text(encoding="utf-8"))
cache = str(UI["asset_revision"])


def test_v725_visual_layer_is_loaded_last():
    patch = re.search(r'<meta name="blinq-web-patch" content="736-r(\d+)"', INDEX)
    assert patch
    assert f'/blinq-app.css?v={cache}&p={patch.group(1)}' in INDEX
    assert 'final-polish-' not in INDEX


def test_v725_has_five_fixed_hero_slots_and_admin_tabs():
    for i in range(1, 6):
        assert f'HERO_BANNER_{i}' in UI['elements']
    assert 'admin-hero-tabs' in APP
    assert 'Aktívne bannery' in APP
    assert 'Interval automatickej zmeny' in APP
    assert 'data-admin-hero-count' in APP
    assert 'data-admin-hero-seconds' in APP


def test_v725_rotation_is_limited_to_three_to_ten_seconds():
    assert "Math.max(3,Math.min(10,Number(t.value)||6))" in APP
    assert UI['hero_banner']['rotation_seconds'] == 6
    assert UI['hero_banner']['auto_rotate'] is True
    assert UI['hero_banner']['pause_on_hover'] is True


def test_v725_static_banner_config_exposes_five_placeholders():
    main = BANNERS['main_banner']
    assert len(main['slides']) == 5
    assert main['rotation_seconds'] == 6
    assert main['auto_rotate'] is True


def test_v725_background_upload_and_ambient_layers_are_present():
    assert 'data-simple-banner-field="site_background_url"' in APP
    assert "input[data-simple-banner-field=\"site_background_url\"]" in APP
    assert 'body#blinqPremium.blinq-home' in CSS
    assert 'body#blinqPremium.blinq-admin' in CSS
    assert 'radial-gradient' in CSS


def test_v725_admin_uses_single_workarea_frame():
    assert 'body#blinqPremium.blinq-admin #routePanel.route-panel' in CSS
    assert 'border:0!important' in CSS
    assert 'body#blinqPremium.blinq-admin .admin-workarea{' in CSS
    assert 'body#blinqPremium.blinq-admin .admin-panel-v685' in CSS
