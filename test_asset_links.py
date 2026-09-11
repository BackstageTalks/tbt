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
    for plan, variants in assets["account_avatars"].items():
        for _, asset_path in variants.items():
            assert asset_path.startswith("/assets/") and asset_path.endswith(".webp")
            assert (ROOT / "web" / asset_path.lstrip("/")).is_file()



def test_web_links_favicon_background_and_fallback_logic():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert '/assets/blinq_favi.png' in html
    assert "url('/assets/blinq_background.png')" in css
    assert "playerFallbackUrl" in js
    assert "accountAvatarUrl" in js
    assert "tooltipAccountRemaining" in js
