import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))

def test_v659_rotating_main_banner_is_fixed_zone_with_configurable_rotation():
    cfg = _cfg()
    assert tuple(map(int, cfg["ui_revision"].split("."))) >= (6, 5, 9)
    hero = cfg["hero_banner"]
    assert hero["enabled"] is True
    assert 1 <= hero["slot_count"] <= 4
    assert 3 <= hero["rotation_seconds"] <= 300
    assert hero["auto_rotate"] is True
    assert hero["show_dots"] is True
    for i in range(1, 5):
        item = cfg["elements"][f"HERO_BANNER_{i}"]
        assert item["kind"] == "hero_banner"
        assert item["zone"] == "hero"
        assert "watermark" in item

def test_v659_header_and_content_zones_keep_fixed_outer_structure():
    cfg = _cfg()
    assert cfg["header_cta"]["slot_count"] in {0, 1, 2, 3, 4}
    for zone in ("content_top", "content_mid", "content_bottom"):
        row = cfg["content_rows"][zone]
        assert row["slot_count"] in {0, 1, 2, 3, 4}
        assert row["preset"] in {"1", "2", "3", "4"}

def test_v659_source_contains_mobile_safe_rotator_and_admin_controls():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "responsive.css").read_text(encoding="utf-8")
    assert 'id="dashboardHero"' in html
    assert "dashboard-hero-stage" in html
    assert "function renderHeroBanner()" in app
    assert "data-admin-hero-seconds" in app
    assert "rotation_seconds" in app
    assert "dashboard-hero-stage" in css
    assert "@media(max-width:820px)" in css
