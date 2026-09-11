import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_v6510_dashboard_preview_is_compact_and_detail_is_capped():
    cfg = _cfg()
    assert tuple(map(int, cfg["ui_revision"].split("."))) >= (6, 5, 10)
    assert 3 <= cfg["dashboard"]["detail_pick_limit"] <= 5
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "responsive.css").read_text(encoding="utf-8")
    assert "dashboard-preview-card" in app
    assert "signals.hidden=true" in app
    assert "analysis.hidden=true" in app
    assert "marketPreviewCard(row,key,absoluteIndex,locked,true)" in app
    assert "#predictionsView .dashboard-preview-card .analysis-link" in css


def test_v6510_rotating_hero_admin_stays_configurable():
    cfg = _cfg()
    hero = cfg["hero_banner"]
    assert hero["enabled"] is True
    assert 1 <= hero["slot_count"] <= 4
    assert 3 <= hero["rotation_seconds"] <= 300
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "data-admin-hero-seconds" in app
    assert "Math.max(3,Math.min(300" in app
