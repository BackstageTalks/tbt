from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
AUTH = (ROOT / 'web' / 'auth.js').read_text(encoding='utf-8')
API = (ROOT / 'api' / 'function_app.py').read_text(encoding='utf-8')


def test_rookie_is_internal_but_free_is_public_label():
    assert "if(id==='rookie')return 'FREE';" in APP
    assert "if(String(plan||'').toLowerCase()==='rookie')return 'FREE';" in APP
    assert "planLabel=plan==='rookie'?'FREE'" in APP


def test_expired_user_can_self_reactivate_only_to_free_rookie():
    assert '/api/v1/account/reactivate-free' in AUTH
    assert 'data-reactivate-free' in APP
    assert '@app.route(route="v1/account/reactivate-free", methods=["POST"])' in API
    assert '{"role": "user", "plan": "rookie", "status": "active", "expires_at": None}' in API
    assert 'if status != "expired"' in API
    assert 'if is_suspended(user)' in API
    assert 'if is_admin(user)' in API


def test_account_membership_uses_detail_description_not_internal_note():
    assert "const detail=String(p.description||'').trim()" in APP
    assert "const featureHeading=String(p?.note||'').trim();" in APP
    assert 'upgrade-feature-heading' in APP
