"""Guard release verification against stale production HTML/CSS."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_css_is_short_cached_only_with_deploy_versioning():
    cfg = json.loads((ROOT / "web/staticwebapp.config.json").read_text(encoding="utf-8"))
    routes = {item["route"]: item for item in cfg["routes"]}
    header = routes["/blinq-app.css"]["headers"]["Cache-Control"]
    assert "public" in header and "max-age=300" in header
    assert "must-revalidate" in header and "no-store" not in header
    assert "/blinq-app.css?v=" in (ROOT / "web/index.html").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "Exact Git SHA and all four deployed asset hashes: PASS" in workflow
    assert "Verify production browser-cache policy for stamped assets" in workflow


def test_deployed_patch_must_match_checkout():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = json.loads((ROOT / "web/release.json").read_text(encoding="utf-8"))
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert f'blinq-web-patch" content="{release["patch"]}"' in index
    assert "json.load(open('web/release.json', encoding='utf-8'))" in workflow
    assert "('release patch', release.get('patch') == expected.get('patch'))" in workflow
    assert "('web patch meta'," in workflow
    assert 'blinq-web-patch" content="' in workflow
    assert "for attempt in 1 2 3 4 5 6 7 8" in workflow
