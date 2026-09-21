from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web/app.js').read_text(encoding='utf-8')
AUTH=(ROOT/'web/auth.js').read_text(encoding='utf-8')
API=(ROOT/'api/function_app.py').read_text(encoding='utf-8')
ADMIN_ACCOUNTS=(ROOT/'api/tbt/services/admin_accounts.py').read_text(encoding='utf-8')
CSS=(ROOT/'web/blinq-app.css').read_text(encoding='utf-8')


def _editor():
    start=APP.index('function renderAdminUserEditor')
    end=APP.index('function renderAdminAccounts', start)
    return APP[start:end]


def test_simple_account_editor_has_only_operational_controls():
    editor=_editor()
    for marker in ['adminUserEmail','adminUserTelegram','<strong>Level</strong>','Platnosť do','reset-user-password','delete-user']:
        assert marker in editor
    for removed in ['Manuálne spárovanie platby','História BlinQ účtu','TG Private','adminPaymentReference','adminUserSuspended','adminUserIsAdmin']:
        assert removed not in editor


def test_plan_presets_and_manual_extension_are_available():
    editor=_editor()
    for plan in ['rookie','pro','elite','legend','goat']:
        assert f'data-admin-user-plan="${{escapeHtml(id)}}"' in editor or plan in APP
    assert 'apply-default-term' in APP
    assert 'extend-default-term' in APP
    assert 'adminAddDaysToExpiry' in APP
    for days in ['30','90','180','365']:
        assert f'data-admin-expiry-days="{days}"' in editor


def test_admin_can_correct_profile_reset_password_and_delete_account():
    assert 'adminUpdateUserProfile' in AUTH
    assert 'adminDeleteUser' in AUTH
    assert 'BlinqAuth.reset(savedEmail)' in APP
    assert 'route="v1/admin/users/{user_id}/profile"' in API
    assert 'route="v1/admin/users/{user_id}"' in API and 'methods=["DELETE"]' in API
    assert 'def update_user_identity' in ADMIN_ACCOUNTS
    assert 'def delete_user_account' in ADMIN_ACCOUNTS


def test_user_list_is_simple_and_sized_for_manual_management():
    assert 'admin-simple-user-row' in APP
    assert 'admin-simple-toolbar' in APP
    assert 'Zobrazených' in APP
    assert 'admin-accounts-split' in APP
    assert '.admin-simple-user-row' in CSS
    assert '.admin-user-editor-simple' in CSS


def test_audit_is_not_exposed_as_primary_admin_navigation():
    route=APP[APP.index('function renderAdminRoute'):APP.index('function rerenderAdmin', APP.index('function renderAdminRoute'))]
    assert "['audit','Audit'" not in route


def test_cookie_banner_never_obscures_admin_workspace():
    assert "if(state.route==='admin'){host.hidden=true;return;}" in APP
    assert "state.route=route;renderCookieConsent(false);" in APP
