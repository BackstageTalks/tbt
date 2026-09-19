from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
CSS=(ROOT/'web'/'blinq-app.css').read_text(encoding='utf-8')
INDEX=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
LOADER=(ROOT/'web'/'assets'/'blinq_loading_animated_v6.svg').read_text(encoding='utf-8')

def test_loader_uses_original_character_scene_and_rally_ball():
    assert '<image ' in LOADER and 'data:image/png;base64,' in LOADER
    assert '<animateTransform' in LOADER and 'repeatCount="indefinite"' in LOADER
    assert 'width:min(420px,78vw)!important' in CSS

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

def test_header_membership_cta_is_subtle():
    assert "label.textContent=lcopy('Membership','Členstvo','Členství')" in APP
    assert 'runtime patch 7.3.6-r21' in CSS
