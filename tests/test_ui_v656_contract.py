from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_v656_mobile_app_navigation_and_responsive_shell():
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    js=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    assert 'id="mobileBottomNav"' in html
    assert 'id="mobileMoreSheet"' in html
    assert 'function syncMobileNavigation()' in js
    assert 'function setMobileMore(open)' in js
    assert '--content-max:1440px' in css
    assert '@media(max-width:820px)' in css
    assert 'scroll-snap-type:x mandatory' in css
    assert '.mobile-bottom-nav' in css


def test_v656_pwa_manifest_and_service_worker():
    html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
    manifest=json.loads((ROOT/'web'/'manifest.webmanifest').read_text(encoding='utf-8'))
    sw=(ROOT/'web'/'sw.js').read_text(encoding='utf-8')
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert manifest['display']=='standalone'
    assert manifest['start_url']=='/#predictions'
    assert {icon['sizes'] for icon in manifest['icons']} >= {'192x192','512x512'}
    assert "navigator.serviceWorker.register('/sw.js')" in (ROOT/'web'/'app.js').read_text(encoding='utf-8')
    assert "blinq-shell-v656" in sw


def test_v656_tablet_bridge_prevents_squeezed_two_column_board():
    css=(ROOT/'web'/'styles.css').read_text(encoding='utf-8')
    assert '@media (min-width:821px) and (max-width:1100px)' in css
    assert '#predictionsView{grid-template-columns:1fr!important}' in css
    assert 'grid-template-areas:"feature" "actions"!important' in css
