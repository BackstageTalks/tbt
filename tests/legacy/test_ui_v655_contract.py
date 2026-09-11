from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))

def test_v655_membership_links_are_external_and_price_free():
    links=json.loads((ROOT / "web" / "membership-links.json").read_text(encoding="utf-8"))
    assert set(links["plans"]) == {"rookie","pro","elite","legend","goat"}
    assert all("payment_url" in row for row in links["plans"].values())
    js=(ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "/membership-links.json" in js
    assert "payment_url||row?.url" in js
    assert "Link not set" not in js

def test_v655_watermark_palette_and_sidebar_destination_editor():
    cfg=_cfg(); js=(ROOT / "web" / "app.js").read_text(encoding="utf-8"); css=(ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert {"violet","blue","cyan","gold","slate"} <= set(cfg["watermark_presets"])
    assert "Sidebar banner destination" in js
    assert "Banner click URL" in js
    for preset in ("violet","blue","cyan","gold","slate"):
        assert f".slot-watermark.wm-{preset}" in css

def test_v655_dashboard_zero_visible_blurs_every_preview_card():
    cfg=_cfg(); js=(ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert cfg["admin"]["dashboard_preview_choices"][0] == 0
    assert "0 + Blur remaining = the whole pick preview is blurred." in js
    assert "absoluteIndex>=unlocked" in js
    assert "ent.blur_remaining!==false" in js

def test_v655_full_board_demo_preview_is_admin_only_memory_data():
    js=(ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "Preview full board" in js
    assert "enableDemoBoardPreview" in js
    assert "sample picks are in browser memory and are never published" in js
