from pathlib import Path

from tbt.services.auth import profile_claims
from tbt.services.admin_accounts import _apply_access_metadata

ROOT = Path(__file__).resolve().parents[1]


def test_profile_claim_fallback_is_small_and_non_sensitive():
    user = {
        "app_metadata": {
            "blinq_telegram_nick": "@member_name",
            "blinq_avatar_variant": "w",
            "blinq_tg_private_member": True,
            "blinq_plan": "elite",
        }
    }
    profile = profile_claims(user)
    assert profile["telegram_nick"] == "@member_name"
    assert profile["avatar_variant"] == "w"
    assert profile["tg_private_member"] is True
    assert profile["admin_note"] == ""
    assert profile["payment_reference"] == ""


def test_access_claim_update_preserves_profile_fallback_claims():
    existing = {
        "blinq_telegram_nick": "@member_name",
        "blinq_avatar_variant": "m",
        "blinq_tg_private_member": True,
        "blinq_plan": "elite",
        "blinq_status": "active",
    }
    changes = {
        "role": "user",
        "plan": "pro",
        "status": "active",
        "expires_at": "2026-10-15T00:00:00+00:00",
    }
    claims = _apply_access_metadata(existing, changes)
    assert claims["blinq_telegram_nick"] == "@member_name"
    assert claims["blinq_avatar_variant"] == "m"
    assert claims["blinq_tg_private_member"] is True
    assert claims["blinq_plan"] == "pro"


def test_public_static_copy_avoids_slovak_tipy_and_bety():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8").lower()
    assert "tipy" not in html
    assert "bety" not in html
    assert "naša predikcia" in html
    assert "prémiové predikcie" in html


def test_admin_route_has_single_page_title_source():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    start = app.index("function renderAdminRoute")
    end = app.index("function rerenderAdmin", start)
    admin_renderer = app[start:end]
    assert "<h1>Admin centrum</h1>" not in admin_renderer
    assert "admin-control-toolbar" in admin_renderer


def test_admin_can_copy_safe_diagnostics():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data-admin-action="copy-diagnostics"' in app
    assert "firebase_server_configured" in app
    assert "azure_available" in app
    assert "firestore_available" in app
    assert "connection_string" not in app[app.index("if(action==='copy-diagnostics')"):app.index("if(action==='save-draft')")]
