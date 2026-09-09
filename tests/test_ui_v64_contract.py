import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))

def test_v64_dashboard_sections_are_independently_manageable():
    cfg=_cfg()
    assert tuple(map(int, cfg["ui_revision"].split("."))) >= (6, 5, 4)
    sections=cfg["dashboard"]["sections"]
    assert set(sections) == {"prime","top_daily","value","ace","sg","doubles","results","btts"}
    assert sections["prime"]["dashboard_enabled"] is True
    assert sections["doubles"]["dashboard_enabled"] is False
    assert sections["ace"]["dashboard_enabled"] is True
    assert sections["sg"]["dashboard_enabled"] is False
    assert cfg["dashboard"]["section_order"] == ["prime", "top_daily", "value", "doubles", "ace", "sg"]
    assert cfg["dashboard"]["visible_slots"] == 4
    assert sections["btts"]["sidebar_enabled"] is True
    for section in sections.values():
        assert isinstance(section["sidebar_enabled"], bool)
        assert isinstance(section["dashboard_enabled"], bool)
        assert 1 <= section["dashboard_order"] <= 99
        assert set(section["plans"]) >= {"trial","expired","rookie","pro","elite","goat","legend"}
        assert section["plans"]["trial"] == section["plans"]["rookie"]

def test_v64_top_banner_row_promotes_membership_levels():
    cfg=_cfg()
    assert cfg["content_rows"]["content_top"]["enabled"] is True
    assert cfg["content_rows"]["content_top"]["preset"] == "2+1+1"
    top=[cfg["elements"][f"CONTENT_TOP_{i}"]["content"] for i in range(1,5)]
    assert top[0]["eyebrow"] == "BLINQ PRO"
    assert top[2]["eyebrow"] == "BLINQ ELITE"
    assert top[3]["eyebrow"] == "BLINQ LEGEND"
    assert top[3]["theme"] == "gold"

def test_v64_header_and_control_system_are_consistent():
    html=(ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js=(ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css=(ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert 'id="profileMenuToggle"' in html
    assert 'id="headerLogoutButton"' in html
    assert 'id="upgradeDialog"' in html
    assert "renderAdminDashboardControls" in js
    assert "data-dashboard-field" in js
    assert "lockedPickCard" in js
    assert ".ui-chevron,.carousel-arrow,.market-arrow" in css
    assert ".profile-shell" in css

def test_default_ui_copy_is_english_first():
    auth=(ROOT / "api" / "tbt" / "services" / "auth.py").read_text(encoding="utf-8")
    js=(ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'or "BlinQ Member"' in auth
    assert "translateSignalLabel" in js
    assert "Overall performance" in js
