from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_r44_release_and_final_inactivity_defaults():
    release = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
    ui = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
    assert release["patch"] == ui["ui_patch"] == "736-r53"
    assert ui["account_inactivity"] == {
        "enabled": True,
        "inactive_days": 30,
        "warning_days": 7,
        "notify_admin": True,
        "notify_user": True,
        "auto_expire_rookie": True,
    }


def test_r44_transactional_mail_renderer_is_shared():
    mail = text("api/tbt/services/auth_email.py")
    lifecycle = text("api/tbt/services/account_inactivity.py")
    assert "def render_blinq_email(" in mail
    assert "def send_blinq_transactional_email(" in mail
    assert "blinq_logo_email.png" in mail
    assert "send_blinq_transactional_email" in lifecycle
    assert "BLINQ MEMBERSHIP" in lifecycle
    assert "Tvoje {plan} predplatné končí o {days} dní" in lifecycle
    assert "Zostaň s BlinQ aktívny" in lifecycle
    assert "Tvoj FREE účet expiruje" in lifecycle


def test_r44_paid_notice_markers_are_tied_to_exact_expiry():
    storage = text("api/tbt/services/account_storage.py")
    lifecycle = text("api/tbt/services/account_inactivity.py")
    assert "subscription_expiry_7_for" in storage
    assert "subscription_expiry_3_for" in storage
    assert "subscription_expiry_7_status" in storage
    assert 'status="pending"' in lifecycle
    assert "already_claimed = marker == exact_expiry" in lifecycle
    assert "save_subscription_notice_state" in lifecycle


def test_r44_admin_email_list_supports_plural_setting_and_legacy_alias():
    config = text("api/tbt/config.py")
    lifecycle = text("api/tbt/services/account_inactivity.py")
    app = text("web/app.js")
    assert 'os.getenv("BLINQ_ADMIN_EMAILS"' in config
    assert 'os.getenv("BLINQ_ADMIN_EMAIL"' in config
    assert "def admin_recipients" in lifecycle
    assert "BLINQ_ADMIN_EMAILS" in app


def test_r44_server_activity_is_recorded_and_used_before_expiry():
    auth = text("api/tbt/services/auth.py")
    storage = text("api/tbt/services/account_storage.py")
    lifecycle = text("api/tbt/services/account_inactivity.py")
    assert "def _touch_verified_activity" in auth
    assert "touch_account_activity(uid)" in auth
    assert "def touch_account_activity" in storage
    assert '"last_activity_at"' in storage
    assert '_parse_utc((meta or {}).get("last_activity_at"))' in lifecycle
    assert "latest_user = firebase_get_user" in lifecycle


def test_r44_worker_is_lifecycle_named_but_route_compatible():
    workflow = text(".github/workflows/account-inactivity.yml")
    api = text("api/function_app.py")
    assert "name: Daily account lifecycle review" in workflow
    assert "--max-time 240" in workflow
    assert 'route="v1/internal/account-inactivity-worker"' in api
