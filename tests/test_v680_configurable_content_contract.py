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

def test_loader_uses_uploaded_dark_webp_gif_and_reduced_motion():
    html=(ROOT/"web"/"index.html").read_text(encoding="utf-8")
    animated=(ROOT/"web"/"assets"/"blinq-loader.webp").read_bytes()
    static=(ROOT/"web"/"assets"/"blinq-loader-static.webp").read_bytes()
    gif=(ROOT/"web"/"assets"/"blinq-loader.gif").read_bytes()
    assert "boot-tennis-track" not in html
    assert "/assets/blinq-loader.webp" in html
    assert "/assets/blinq-loader-static.webp" in html
    assert "/assets/blinq-loader.gif" in html
    assert "prefers-reduced-motion: reduce" in html
    assert animated[:4] == b"RIFF" and animated[8:12] == b"WEBP"
    assert b"ANIM" in animated[:4096]
    assert static[:4] == b"RIFF" and static[8:12] == b"WEBP"
    assert gif.startswith((b"GIF87a", b"GIF89a"))

def test_indoor_hard_uses_hard_stats_bucket():
    text=(ROOT/"api"/"tbt"/"models"/"feature_builder.py").read_text(encoding="utf-8")
    assert 'return "hard" if value == "indoor_hard" else value' in text
