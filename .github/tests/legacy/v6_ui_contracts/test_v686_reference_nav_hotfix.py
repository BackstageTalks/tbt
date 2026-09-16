from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/"web/app.js").read_text(encoding="utf-8")
INDEX=(ROOT/"web/index.html").read_text(encoding="utf-8")

def test_reference_navigation_tracks_route_family():
    assert "const modelRoutes=new Set(['model_data','methodology','how_blinq_works'])" in APP
    assert "node.dataset.route===referenceRoute" in APP
    assert "node.setAttribute('aria-current','page')" in APP
    assert "state.route==='results'?'results'" in APP

def test_hotfix_cache_bust():
    assert '/app.js?v=6864' in INDEX
