from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/"web"/"app.js").read_text(encoding="utf-8")
INDEX=(ROOT/"web"/"index.html").read_text(encoding="utf-8")
CSS=(ROOT/"web"/"final-polish-736.css").read_text(encoding="utf-8")

def test_admin_publish_function_is_real_and_calls_api():
    assert "async function publishUiConfig()" in APP
    assert "BlinqAuth.adminSaveUiConfig(state.ui)" in APP
    assert "else if(action==='publish-config')await publishUiConfig();" in APP

def test_access_hint_does_not_flicker_when_pointer_moves_into_hint():
    assert "hint?.contains(next)" in APP
    assert "accessHintNode.addEventListener('pointerenter'" in APP
    assert "accessHintNode.addEventListener('pointerleave'" in APP

def test_minimal_footer_is_visible_on_home_and_legacy_vip_strip_is_hidden():
    assert 'site-footer site-footer-minimal' in INDEX
    assert 'footer-watermark-logo' in INDEX
    assert 'id="footerLanguages"' in INDEX
    assert 'id="footerLearnNavigation"' not in INDEX
    assert 'class="system-status"' not in INDEX
    assert 'body#blinqPremium.blinq-home .site-footer.site-footer-minimal' in CSS
    assert 'body#blinqPremium #vipRail{display:none!important;}' in CSS

def test_patch_cache_marker_is_r9():
    assert 'content="736-r9"' in INDEX
    assert '/app.js?v=7360&p=9' in INDEX
    assert '/final-polish-736.css?v=7360&p=9' in INDEX
