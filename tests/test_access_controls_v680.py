from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_banner_admin_has_all_visibility_and_elite_link_preset():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data-simple-banner-visible="ALL"' in app
    assert 'data-simple-banner-click="ALL"' in app
    assert 'data-banner-preset="teaser-elite"' in app
    assert "['elite','legend','goat'].includes(plan)" in app


def test_pick_count_controls_are_zero_to_ten_plus_all():
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    assert cfg["admin"]["dashboard_preview_choices"] == [0,1,2,3,4,5,6,7,8,9,10,"ALL"]
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "[0,1,2,3,4,5,6,7,8,9,10,'ALL']" in app
    assert "['daily','top','value','ace','games','doubles']" in app


def test_public_low_odds_label_is_short_odds():
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    assert cfg["dashboard"]["sections"]["prime"]["label"] == "Short Odds"
    assert cfg["dashboard"]["daily_hub"]["tabs"]["top"]["label"] == "Short Odds"
