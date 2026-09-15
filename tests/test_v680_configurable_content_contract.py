from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]

def test_editable_json_files_exist_and_parse():
    for name in ["membership-tiers.json","banners.json","footer-links.json","site-theme.json"]:
        data=json.loads((ROOT/"web"/"config"/name).read_text(encoding="utf-8"))
        assert data.get("schema") == 1

def test_banners_support_ads_mode():
    data=json.loads((ROOT/"web"/"config"/"banners.json").read_text(encoding="utf-8"))
    assert any(x.get("mode")=="ads" for x in data["home_small_banners"]["slides"])

def test_goat_is_regular_upgrade_tier():
    data=json.loads((ROOT/"web"/"config"/"membership-tiers.json").read_text(encoding="utf-8"))
    goat=data["tiers"]["goat"]
    assert goat["cta_label"] == "Upgrade na GOAT"
    assert goat["invite_only"] is False

def test_loader_has_track_and_moving_ball():
    html=(ROOT/"web"/"index.html").read_text(encoding="utf-8")
    css=(ROOT/"web"/"blinq.css").read_text(encoding="utf-8")
    assert "boot-tennis-track" in html and "blinqLoadingBall" in css

def test_indoor_hard_uses_hard_stats_bucket():
    text=(ROOT/"api"/"tbt"/"services"/"feature_builder.py").read_text(encoding="utf-8")
    assert 'return "hard" if value == "indoor_hard" else value' in text
