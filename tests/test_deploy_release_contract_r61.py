"""Guard release verification against stale production HTML/CSS."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_css_is_not_cached():
    cfg = json.loads((ROOT / "web/staticwebapp.config.json").read_text(encoding="utf-8"))
    routes = {item["route"]: item for item in cfg["routes"]}
    header = routes["/blinq-app.css"]["headers"]["Cache-Control"]
    assert "no-store" in header
    assert "must-revalidate" in header


def test_deployed_patch_must_match_checkout():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = json.loads((ROOT / "web/release.json").read_text(encoding="utf-8"))
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert f'blinq-web-patch" content="{release["patch"]}"' in index
    assert "json.load(open('web/release.json', encoding='utf-8'))" in workflow
    assert "assert data.get('patch') == expected.get('patch')" in workflow
    assert 'grep -q "blinq-web-patch' in workflow
