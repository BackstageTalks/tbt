from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
RELEASE = json.loads((ROOT/'web'/'release.json').read_text(encoding='utf-8'))
PATCH = str(RELEASE['patch'])
PATCH_NUM = PATCH.rsplit('r',1)[-1]
APP=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
CSS=(ROOT/'web'/'blinq-app.css').read_text(encoding='utf-8')
INDEX=(ROOT/'web'/'index.html').read_text(encoding='utf-8')

def test_loader_uses_approved_picture_with_reduced_motion_and_fallbacks():
    picture = INDEX.split('<picture class="blinq-loader-media">', 1)[1].split('</picture>', 1)[0]
    assert 'media="(prefers-reduced-motion: reduce)"' in picture
    assert '/assets/blinq-loader-static.webp' in picture
    assert '/assets/blinq-loader.webp' in picture
    assert '/assets/blinq-loader.gif' in picture
    for name in ('blinq-loader.webp', 'blinq-loader.gif', 'blinq-loader-static.webp'):
        assert (ROOT / 'web' / 'assets' / name).is_file()
    for retired in ('blinq_loading_r29.svg', 'blinq_loading_r2911.svg',
                    'blinq_loading_animated_v6.svg', 'blinq_loading_scene_v736.webp'):
        assert not (ROOT / 'web' / 'assets' / retired).exists()
    assert '/assets/blinq_loading_scene_v736.webp' not in CSS
    assert '--blinq-login-loader-backdrop' in CSS


def test_results_cleanup_removes_redundant_copy():
    assert 'results-access-note is-full' not in APP
    assert 'results-section-head results-section-clean' in APP
    assert "pageEyebrow.hidden=route==='results'" in APP
    assert "pageSubtitle.hidden=route==='results'" in APP

def test_editable_public_labels_can_be_blank():
    assert "Object.prototype.hasOwnProperty.call(c,'eyebrow')" in APP
    assert "data-tg-group-field=\"badge\"" in APP
    assert "badge?`<small>" in APP

def test_system_diagnostics_is_single_read_only_action():
    assert APP.count('>Obnoviť diagnostiku</button>') == 1
    assert 'Kontrola je len čítacia diagnostika' in APP
    assert 'Nič neopravuje a nespúšťa data/enrichment run ani LIVE scan.' in APP

def test_live_worker_setup_is_explained_in_system():
    assert 'BLINQ_LIVE_WORKER_TOKEN' in APP
    assert 'TBT_LIVE_RADAR_ENABLED=true' in APP

def test_header_upgrade_cta_is_clear_and_compact():
    assert "label.textContent=lcopy('Upgrade','Upgrade','Upgrade')" in APP
    assert 'id="topUpgradeLabel">Upgrade</span></button>' in INDEX
    assert f"runtime patch 7.3.6-r{PATCH_NUM}" in CSS
