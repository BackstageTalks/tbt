from pathlib import Path


def test_login_does_not_block_legacy_firebase_passwords_in_html():
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="authPassword" minlength="8"' not in html


def test_login_password_policy_is_mode_aware():
    js = Path("web/app.js").read_text(encoding="utf-8")
    assert "minLength=(mode==='signup'||mode==='recovery')?8:0" in js
    assert "password.length<8" in js


def test_auth_assets_are_cache_busted_to_6532():
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert "/auth.js?v=6532" in html
    assert "/app.js?v=6532" in html
    assert "/styles.css?v=6532" in html
