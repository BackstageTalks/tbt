import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def ui():
    return json.loads(read("ui-config.json"))


def test_v700_revision_is_active():
    cfg = ui()
    assert cfg["revision"] == cfg["ui_revision"] == "7.3.3"


def test_v700_public_prediction_categories_are_current():
    tabs = ui()["dashboard"]["daily_hub"]["tabs"]
    assert tabs["daily"]["label"] == "TOP" and tabs["daily"]["enabled"] is True
    assert tabs["value"]["label"] == "VALUE" and tabs["value"]["enabled"] is True
    assert tabs["ace"]["label"] == "ESA" and tabs["ace"]["enabled"] is True
    assert tabs["games"]["label"] == "GAMES" and tabs["games"]["enabled"] is True
    # PRIME/Short Odds is internal, not a public prediction tab.
    assert tabs["prime"]["enabled"] is False
    assert tabs["top"]["enabled"] is False
    assert tabs["doubles"]["enabled"] is False
    assert tabs["board"]["enabled"] is False


def test_v700_core_web_assets_exist_and_are_wired():
    html = read("index.html")
    js = read("app.js")
    assert "app.js" in html
    assert "ui-config.json" in js
    assert "TOP" in html or "TOP" in js
    assert "VALUE" in html or "VALUE" in js
