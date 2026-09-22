import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_is_r41():
    release = json.loads(_text("web/release.json"))
    ui = json.loads(_text("web/ui-config.json"))
    assert release["patch"] == ui["ui_patch"] == "736-r55"
    assert 'content="736-r55"' in _text("web/index.html")
    assert "const AUTH_RUNTIME = '736-r55'" in _text("web/auth.js")


def test_b12_password_reset_public_response_is_enumeration_safe():
    api = _text("api/function_app.py")
    block = api.split('@app.route(route="v1/auth/email", methods=["POST"])', 1)[1].split('@app.route(route="v1/auth/me"', 1)[0]
    reset = block.split('recipient = str(payload.get("email")', 1)[1].split('    except ValueError as exc:',1)[0]
    assert "claim_auth_email_slot(recipient, \"reset\"" in reset
    assert "firebase_get_user_by_email(settings, recipient)" in reset
    assert "BlinQ password-reset delivery suppressed after internal failure" in reset
    # Internal Firebase/storage/SMTP failures are swallowed for reset only.
    assert reset.count('return response({"ok": True, "accepted": True})') >= 3
    assert 'return response({"error": "email_delivery_unavailable"}, 503)' not in reset


def test_b12_auth_email_has_durable_cross_instance_cooldown():
    service = _text("api/tbt/services/auth_email.py")
    assert '_AUTH_EMAIL_THROTTLE_TABLE = "BlinQAuthEmailThrottle"' in service
    assert "def claim_auth_email_slot" in service
    assert "hashlib.sha256" in service
    assert ".create_entity(entity)" in service
    assert '"alreadyexists" in name' in service
    api = _text("api/function_app.py")
    assert "_AUTH_EMAIL_RATE_MAX_REQUESTS = 20" in api
    assert "def _auth_email_request_allowed(req)" in api


def test_b18_ui_requests_are_bounded_and_parallelized():
    app = _text("web/app.js")
    assert "async function getJSON(url,{timeoutMs=4000}={})" in app
    assert "controller.abort()" in app
    assert "UI_REQUEST_TIMEOUT" in app
    assert "Promise.allSettled([" in app
    assert "getJSON('/api/v1/ui-config',{timeoutMs:3500})" in app
    assert "getJSON('/membership-links.json',{timeoutMs:3000})" in app


def test_b18_news_does_not_block_authenticated_workspace_commit():
    app = _text("web/app.js")
    feed_block = app.split("async function loadFeed(showLoading=true)", 1)[1].split("async function refreshWorkspace", 1)[0]
    assert "await loadNewsPool()" not in feed_block
    assert "loadNewsPool().then" in feed_block
    auth = _text("web/auth.js")
    assert "contentNews() { return json('/api/v1/content/news',{timeoutMs:5000}); }" in auth


def test_b19_signup_persists_new_identity_before_profile_side_effect():
    auth = _text("web/auth.js")
    block = auth.split("async function signUpFirebase", 1)[1].split("async function signUp(", 1)[0]
    assert block.index("replaceSession(data, 'firebase')") < block.index("syncPendingRegistrationProfile")
    assert "savePendingRegistrationProfile(normalizedEmail,profilePayload)" in block
    assert "profile_pending: !profileSynced" in block
    assert "if(profileSynced&&!emailDeliveryError) clear();" in block
    assert "email_delivery_failed: Boolean(emailDeliveryError)" in block


def test_b19_pending_profile_has_reload_and_signin_recovery():
    auth = _text("web/auth.js")
    assert "PENDING_PROFILE_KEY = 'blinq_v4_pending_registration_profile'" in auth
    assert "async function syncPendingRegistrationProfile" in auth
    signin = auth.split("async function signInFirebase", 1)[1].split("async function signIn(", 1)[0]
    assert "await syncPendingRegistrationProfile(data.idToken,email)" in signin
    resend = auth.split("async function resendVerification", 1)[1].split("async function resetFirebase", 1)[0]
    assert "syncPendingRegistrationProfile(s.access_token)" in resend


def test_b20_popout_uses_external_csp_safe_runtime_and_asset_fallbacks():
    app = _text("web/app.js")
    popout = app.split("function openMatchPopout()", 1)[1].split("function openMatch(", 1)[0]
    assert 'src="/match-popout.js?v=7360&p=55"' in popout
    assert "document.addEventListener('click',function" not in popout
    runtime = _text("web/match-popout.js")
    assert "[data-match-tab]" in runtime
    assert "[data-player-photo]" in runtime
    assert "data-fallback-src" not in runtime  # accessed via dataset, not unsafe HTML rewrite
    assert "img.dataset.fallbackSrc" in runtime
    swa = json.loads(_text("web/staticwebapp.config.json"))
    csp = swa["globalHeaders"]["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    routes = {row.get("route"): row for row in swa["routes"]}
    assert "/match-popout.js" in routes
    assert "no-store" in routes["/match-popout.js"]["headers"]["Cache-Control"]


def test_b12_durable_throttle_claim_is_atomic(monkeypatch):
    from tbt.services import auth_email

    seen = set()

    class ExistsError(Exception):
        status_code = 409

    class FakeTable:
        def create_entity(self, entity):
            key = (entity["PartitionKey"], entity["RowKey"])
            if key in seen:
                raise ExistsError("already exists")
            seen.add(key)

    monkeypatch.setattr(auth_email, "_table", lambda name: FakeTable())
    assert auth_email.claim_auth_email_slot("member@example.com", "reset", window_seconds=900) is True
    assert auth_email.claim_auth_email_slot("member@example.com", "reset", window_seconds=900) is False
    assert auth_email.claim_auth_email_slot("other@example.com", "reset", window_seconds=900) is True
