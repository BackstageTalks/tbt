from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def _cfg():
    return json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))

def test_v654_public_promos_exclude_goat_and_keep_pro_elite_legend():
    cfg = _cfg()
    assert cfg["ui_revision"] == "6.5.5"
    assert [cfg["elements"][f"HEADER_BANNER_{i}"]["content"]["eyebrow"] for i in (1,2,3)] == ["BLINQ PRO", "BLINQ ELITE", "BLINQ LEGEND"]
    assert cfg["elements"]["CONTENT_TOP_4"]["content"]["eyebrow"] == "BLINQ LEGEND"
    assert "BLINQ GOAT" not in (ROOT / "web" / "ui-config.json").read_text(encoding="utf-8")

def test_v654_logo_signature_and_admin_only_dashboard_controls():
    css=(ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    js=(ROOT / "web" / "app.js").read_text(encoding="utf-8")
    cfg=_cfg()
    assert ".engine-copy{width:126px" in css
    assert "padding-left:3px" in css
    assert "letter-spacing:.18em" in css
    assert cfg["dashboard"]["user_switches"] is False
    assert cfg["dashboard"]["show_disabled_strip"] is False
    assert "Dashboard pick display" in js
    assert "Replace an empty window with the next section that has published picks" in js

def test_v654_health_and_selection_schema_contract():
    api=(ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    sel=(ROOT / "api" / "tbt" / "services" / "market_selection.py").read_text(encoding="utf-8")
    assert '"version": "3.4.4"' in api
    assert '"schema": 10' in sel
    assert 'prime_top_value_v7_min5_before_expand' in sel
