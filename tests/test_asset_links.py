import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_static_asset_contract_is_configured():
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    assets = cfg["assets"]
    assert assets["favicon"] == "/assets/blinq_favi.png"
    assert assets["background"] == "/assets/blinq_background.png"
    assert assets["player_fallback"] == {
        "atp": "/assets/missing_foto_m.png",
        "wta": "/assets/missing_foto_w.png",
    }
    assert assets["account_avatars"]["rookie"]["m"] == "/assets/rookie_m.webp"
    assert assets["account_avatars"]["rookie"]["w"] == "/assets/rookie_w.webp"
    assert assets["account_avatars"]["pro"]["m"] == "/assets/pro_m.webp"
    assert assets["account_avatars"]["elite"]["w"] == "/assets/elite_w.webp"
    assert assets["account_avatars"]["legend"]["m"] == "/assets/legend_m.webp"
    assert assets["account_avatars"]["goat"]["default"] == "/assets/goat.webp"


def test_web_links_favicon_background_and_fallback_logic():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert '/assets/blinq_favi.png' in html
    assert "url('/assets/blinq_background.png')" in css
    assert "playerFallbackUrl" in js
    assert "accountAvatarUrl" in js
    assert "blinq_avatar_variant" in js
