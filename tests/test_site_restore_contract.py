"""Prevent UI/config rollback through an old queued Azure deployment."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "stamp_web_deployment", ROOT / "scripts" / "stamp_web_deployment.py"
)
assert spec and spec.loader
stamp_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stamp_module)


def test_deployment_stamps_current_git_sha_and_cache_busts_all_assets(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    sha = "a" * 40
    (web / "release.json").write_text(
        json.dumps({"patch": "736-r61", "visual_revision": "approved-visuals"}),
        encoding="utf-8",
    )
    (web / "index.html").write_text(
        '<title>BlinQ · Tennis Intelligence</title>\n'
        '<link rel="stylesheet" href="/blinq-app.css?v=7360&p=61">\n'
        '<script src="/auth.js?v=7360&p=61"></script>\n'
        '<script src="/responsive.js?v=7360&p=61"></script>\n'
        '<script src="/app.js?v=7360&p=61"></script>\n',
        encoding="utf-8",
    )
    for name in stamp_module.ASSETS:
        (web / name).write_text("actual web code: " + name, encoding="utf-8")
    first = stamp_module.stamp(web, sha)
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'blinq-deployment-sha" content="' + sha in html
    assert html.count("&deploy=" + sha[:12]) == 4
    assert first["git_sha"] == sha
    assert len(first["files_sha256"]) == 4
    assert json.loads((web / "deployment.json").read_text()) == first
    # Re-running the same stamp is safe and cannot accumulate query parameters.
    second = stamp_module.stamp(web, sha)
    assert second == first
    assert (web / "index.html").read_text(encoding="utf-8") == html


def test_stale_deploy_preflight_in_both_deployment_paths():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    data = (ROOT / ".github" / "workflows" / "data.yml").read_text(encoding="utf-8")
    for workflow in (ci, data):
        assert "stamp_web_deployment.py" in workflow
        assert "git fetch origin main --depth=1" in workflow
        assert workflow.rfind("stamp_web_deployment.py") < workflow.rfind(
            "uses: Azure/static-web-apps-deploy@v1"
        )
    assert "files_sha256" in ci and "blinq-deployment-sha" in ci


def test_runtime_config_never_treats_release_fallback_as_saved_admin_content():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "runtime?.runtime_configured===true" in app
    assert "runtime?.storage_available===true" in app
    assert "blinq_last_verified_runtime_ui_v1" in app
    assert "if(state.uiStorageAvailable!==true)" in app
    assert "state.runtimeConfigLoaded&&status?.runtime_configured!==true" in app


def test_no_stale_cache_on_spa_alias_and_cms_configs():
    cfg = json.loads((ROOT / "web" / "staticwebapp.config.json").read_text())
    routes = {entry["route"]: entry for entry in cfg["routes"]}
    for route in ("/", "/index.html", "/follow-the-data/", "/deployment.json", "/config/*"):
        assert "no-store" in routes[route]["headers"]["Cache-Control"]
    assert routes["/follow-the-data/"]["rewrite"] == "/index.html"
