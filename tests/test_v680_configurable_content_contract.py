from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]

def test_editable_json_files_exist_and_parse():
    for name in ["membership-tiers.json","banners.json","site-theme.json","site-content.json"]:
        data=json.loads((ROOT/"web"/"config"/name).read_text(encoding="utf-8"))
        assert data.get("schema") in {1, 2}

def test_retired_home_small_banner_feed_is_removed():
    data=json.loads((ROOT/"web"/"config"/"banners.json").read_text(encoding="utf-8"))
    assert "home_small_banners" not in data
    assert not (ROOT/"web"/"config"/"footer-links.json").exists()

def test_goat_is_regular_upgrade_tier():
    data=json.loads((ROOT/"web"/"config"/"membership-tiers.json").read_text(encoding="utf-8"))
    goat=data["tiers"]["goat"]
    assert goat["cta_label"] == "Upgrade na GOAT"
    assert goat["invite_only"] is False

def test_loader_is_compact_svg_rally_without_progress_track():
    html=(ROOT/"web"/"index.html").read_text(encoding="utf-8")
    loader=(ROOT/"web"/"assets"/"blinq_loading_r29.svg").read_text(encoding="utf-8")
    assert "boot-tennis-track" not in html
    assert "/assets/blinq_loading_r29.svg" in html
    assert "<animateTransform" in loader
    assert 'aria-label="BlinQ animated loading screen"' in loader

def test_indoor_hard_uses_hard_stats_bucket():
    text=(ROOT/"api"/"tbt"/"models"/"feature_builder.py").read_text(encoding="utf-8")
    assert 'return "hard" if value == "indoor_hard" else value' in text
