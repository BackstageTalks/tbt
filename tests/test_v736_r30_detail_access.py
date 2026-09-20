import json
from copy import deepcopy
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config
from tbt.services.entitlements import entitlement_manifest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
APP = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
FUNCTION_APP = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")


def access(plan):
    return {"plan": plan, "status": "active", "role": "user", "is_admin": False}


def test_r30_release_and_default_detail_rule():
    assert UI["ui_patch"] == "736-r30"
    assert UI["dashboard"]["daily_hub"]["detail_min_level"] == "rookie"
    assert 'content="736-r30"' in INDEX
    for asset in ("app.js", "auth.js", "responsive.js", "blinq-app.css"):
        assert f"/{asset}?v=7360&p=30" in INDEX


def test_detail_min_level_is_validated_and_server_manifest_enforces_it():
    cfg = deepcopy(UI)
    cfg["dashboard"]["daily_hub"]["detail_min_level"] = "elite"
    validate_ui_config(cfg)
    assert entitlement_manifest(access("rookie"), {}, cfg)["details"] == {"enabled": False, "min_level": "elite"}
    assert entitlement_manifest(access("pro"), {}, cfg)["details"] == {"enabled": False, "min_level": "elite"}
    assert entitlement_manifest(access("elite"), {}, cfg)["details"] == {"enabled": True, "min_level": "elite"}
    admin = {"plan": "admin", "status": "active", "role": "admin", "is_admin": True}
    assert entitlement_manifest(admin, {}, cfg)["details"]["enabled"] is True


def test_invalid_detail_min_level_cannot_publish():
    cfg = deepcopy(UI)
    cfg["dashboard"]["daily_hub"]["detail_min_level"] = "diamond"
    try:
        validate_ui_config(cfg)
    except ValueError as exc:
        assert "detail minimum" in str(exc).lower()
    else:
        raise AssertionError("invalid detail minimum level was accepted")


def test_frontend_has_one_global_dynamic_detail_gate_and_admin_control():
    assert "function predictionDetailAccess()" in APP
    assert "function predictionDetailButton(available=true)" in APP
    assert "function ensurePredictionDetailAccess(source=null)" in APP
    assert "data-admin-detail-min-level" in APP
    assert "Detail predikcie" in APP
    assert "if(!ensurePredictionDetailAccess(row))return" in APP


def test_live_match_intelligence_is_server_gated_too():
    assert '"detail_access_required"' in FUNCTION_APP
    assert 'hub_cfg.get("detail_min_level")' in FUNCTION_APP
    assert "_membership_allowed(account_data, detail_min)" in FUNCTION_APP


def test_r30_detail_visual_is_compact_centered_and_mobile_safe():
    marker = "BlinQ runtime patch 7.3.6-r30 — unified compact detail workspace"
    assert marker in CSS
    tail = CSS[CSS.index(marker):]
    assert "width:min(760px,calc(100vw - 40px))" in tail
    assert "max-height:min(88dvh,820px)" in tail
    assert "min-height:0!important" in tail
    assert "inset:auto 0 0 0!important" in tail
    assert ".admin-detail-access-card" in tail


def test_locked_feed_strips_detail_only_projection_fields():
    from tbt.services.entitlements import _strip_prediction_detail_fields
    rows = [{
        "event_id": "e1", "pick": "A", "projection": 4.2, "projection_confidence": .71,
        "opponent_projection": 2.1, "projection_gap": 2.1,
        "projection_samples": {"player1": 18, "player2": 17},
        "projection_source": "historical_event_statistics",
        "reference_projection": 3.9, "baseline_projection": 3.8,
    }]
    safe = _strip_prediction_detail_fields(rows)
    assert safe[0]["projection"] == 4.2
    assert safe[0]["projection_confidence"] == .71
    for key in ("projection_samples", "projection_gap", "opponent_projection", "projection_source", "reference_projection", "baseline_projection"):
        assert key not in safe[0]
    # Filtering must not mutate the source payload.
    assert rows[0]["projection_samples"]["player1"] == 18


def test_ace_open_has_defensive_detail_access_gate():
    assert "if(!aceProjectionDetailAvailable(row)||!ensurePredictionDetailAccess())return;" in APP
