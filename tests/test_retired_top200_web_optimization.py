"""TOP200 is retired from the public/admin offer; old URLs remain harmless."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_top200_is_absent_from_all_public_and_server_default_ui():
    for file in ("web/ui-config.json", "api/tbt/assets/ui_access_defaults.json"):
        cfg = json.loads((ROOT / file).read_text(encoding="utf-8"))
        serialized = json.dumps(cfg, ensure_ascii=False).lower()
        assert "top200" not in serialized, file
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert 'id="top200Panel"' not in html


def test_legacy_top200_url_redirects_without_restoring_ui_or_old_feed():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert "if(route==='top200')route='predictions'" in app
    assert "if(route==='top200'){setRoute('predictions');return;}" in app
    assert "if(key==='top200')return []" in app
    assert "    top200:{label:'TOP200'" not in app
    assert "marketRows('top200')" not in app
    assert "state.ui.market_rules.top200" in app  # legacy runtime config is deleted
    assert "delete state.ui.elements.SIDEBAR_TOP200" in app
    assert "filter(key=>key!=='top200')" in app


def test_optimizer_does_not_change_committed_sources_or_identifiers():
    script = (ROOT / "scripts/optimize_web_assets.py").read_text(encoding="utf-8")
    assert '"--minify-whitespace"' in script
    assert '--mangle' not in script
    assert '--minify-syntax' not in script
    assert '--minify-identifiers' not in script
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "tests/browser_optimized_assets.py" in ci
    assert "python scripts/optimize_web_assets.py --web web" in ci
    assert ci.index("Run real-browser runtime contract") < ci.index("Verify optimized JS/CSS in real Chromium")
    assert ci.index("Build safe whitespace-only optimized production JS/CSS") < ci.index("Reject queued stale deploy")
