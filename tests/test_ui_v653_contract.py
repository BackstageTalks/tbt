from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_v653_header_geometry_and_brand_contract():
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert "--dashboard-header-height:92px" in css
    assert "display:grid!important" in css
    assert "width:clamp(520px,34vw,720px)" in css
    assert "grid-template-columns:minmax(118px,.72fr) minmax(260px,1.55fr) minmax(112px,.70fr)" in css
    assert ".engine-brand .brand-logo" in css
    assert "width:126px" in css
    assert "justify-items:center" in css


def test_v653_header_promos_and_revision_contract():
    config = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert config["ui_revision"] == "6.5.3"
    assert config["elements"]["HEADER_BANNER_1"]["content"]["eyebrow"] == "BLINQ PRO"
    assert config["elements"]["HEADER_BANNER_2"]["content"]["eyebrow"] == "BLINQ ELITE"
    assert config["elements"]["HEADER_BANNER_3"]["content"]["eyebrow"] == "BLINQ LEGEND"
    assert "'HEADER_BANNER_1','HEADER_BANNER_2','HEADER_BANNER_3'" in js


def test_v653_health_version_contract():
    api = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    assert '"version": "3.4.3"' in api
