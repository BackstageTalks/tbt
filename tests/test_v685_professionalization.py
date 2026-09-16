from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
API = ROOT / 'api'


def test_professionalization_assets_are_loaded():
    html=(WEB/'index.html').read_text(encoding='utf-8')
    assert '/polish-685.css?v=6860' in html
    assert '/app.js?v=6860' in html
    assert '/auth.js?v=6860' in html
    assert 'publicContentDialog' in html
    assert 'cookieConsent' in html
    assert 'authLegalConsent' in html


def test_site_content_has_all_public_pages_in_all_locales():
    data=json.loads((WEB/'config'/'site-content.json').read_text(encoding='utf-8'))
    required={'how_blinq_works','methodology','model_data','faq','responsible_use','terms','privacy','cookies','support'}
    for locale in ('sk','cz','en'):
        assert required.issubset(data['pages'][locale])
        for key in required:
            assert data['pages'][locale][key].get('title')
    assert data['support']['categories']
    assert set(data['cookie_banner']) == {'sk','cz','en'}


def test_footer_links_expose_legal_and_support_pages():
    data=json.loads((WEB/'ui-config.json').read_text(encoding='utf-8'))
    ids={item['id'] for item in data['footer']['links'] if item.get('enabled', True)}
    assert {'terms','privacy','cookies','support'}.issubset(ids)


def test_admin_workspace_contains_new_operational_sections():
    js=(WEB/'app.js').read_text(encoding='utf-8')
    for marker in ['admin-console-v685', "['support','Support'", "['audit','Audit'", "['system','System'", "['pages','Obsah'"]:
        assert marker in js
    assert 'renderAdminSupport' in js
    assert 'renderAdminAudit' in js
    assert 'renderAdminSystem' in js
    assert 'renderAdminPages' in js


def test_manual_payment_ledger_and_account_history_exist():
    js=(WEB/'app.js').read_text(encoding='utf-8')
    auth=(WEB/'auth.js').read_text(encoding='utf-8')
    storage=(API/'tbt'/'services'/'account_storage.py').read_text(encoding='utf-8')
    assert 'Pridať platbu do histórie' in js
    assert 'História BlinQ účtu' in js
    assert 'adminAddPayment' in auth
    assert 'record_manual_payment' in storage
    assert 'list_manual_payments' in storage
    assert 'list_account_audit' in storage
    # Never nest a second form inside the account editor.
    assert '<form id="adminPaymentForm"' not in js
    assert '<div id="adminPaymentForm"' in js


def test_support_and_observability_backend_endpoints_exist():
    fn=(API/'function_app.py').read_text(encoding='utf-8')
    for route in ['v1/support','v1/admin/support','v1/admin/users/{user_id}/payments','v1/admin/audit']:
        assert f'route="{route}"' in fn
    assert '"feed": feed_health' in fn
    assert '"provider": provider_health' in fn
    assert '"ops": ops' in fn


def test_optional_analytics_is_consent_gated():
    js=(WEB/'app.js').read_text(encoding='utf-8')
    assert "cookieConsentKey='blinq_cookie_consent_v1'" in js
    assert 'analyticsConsentAllowed()' in js
    assert "if(!node?.dataset?.bannerSlot||!analyticsConsentAllowed())return;" in js


def test_signup_requires_legal_consent():
    js=(WEB/'app.js').read_text(encoding='utf-8')
    assert "if(!$('authLegalConsent')?.checked)" in js
    assert 'Podmienky používania a Ochranu súkromia' in js
