from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
AUTH = (ROOT / 'web' / 'auth.js').read_text(encoding='utf-8')
HTML = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')


def test_login_modal_is_not_closed_before_feed_authorizes_account():
    assert "if($('authDialog').open) $('authDialog').close(); await loadFeed();" not in APP
    assert "await loadFeed();" in APP
    assert "feed loader closes it only after a successful authenticated response" in APP


def test_unverified_email_is_explicitly_detected_during_firebase_signin():
    assert "const verified = await firebaseEmailVerified(data.idToken);" in AUTH
    assert "error.code = 'EMAIL_NOT_VERIFIED';" in AUTH
    assert "replaceSession(data, 'firebase');" in AUTH


def test_auth_failures_are_rendered_in_login_modal():
    assert "account_suspended" in APP
    assert "if(!$('authDialog').open)$('authDialog').showModal();" in APP
    assert "The BlinQ workspace could not be opened." in APP


def test_assets_are_cache_busted_to_6534():
    for asset in ('styles.css', 'responsive.css', 'premium.css', 'auth.js', 'responsive.js', 'app.js'):
        assert f'/{asset}?v=6534' in HTML
