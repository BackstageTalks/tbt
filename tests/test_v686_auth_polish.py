from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'

def read(name): return (WEB/name).read_text(encoding='utf-8')

def test_auth_polish_asset_and_copy_are_active():
    html=read('index.html'); js=read('app.js')
    assert '/auth-polish-686.css?v=6860' in html
    assert 'STATISTICAL ENGINE · BACKSTAGETALKS' not in html
    assert 'Vitaj späť.' not in html
    assert "login:'Sign in to your analytics workspace'" in js
    assert "signup:'Get access'" in js
    assert "reset:'Restore your access'" in js
    assert "recovery:'Set a new password'" in js
    assert "$('authDialog').dataset.mode=mode" in js

def test_signup_marks_all_three_fields_required_and_has_telegram_icon():
    html=read('index.html'); js=read('app.js')
    assert 'auth-telegram-icon' in html
    assert html.count('class="auth-required"') == 3
    assert "$('authName').required=mode==='signup'" in js
    assert "$('authEmail').required=mode!=='recovery'" in js
    assert "$('authPassword').required=mode!=='reset'" in js

def test_legal_consent_is_compact_and_not_purple():
    css=read('auth-polish-686.css')
    assert 'input[type="checkbox"]' in css
    assert 'width:15px!important' in css
    assert '#39e7a2' in css
