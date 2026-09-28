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
        '  <title>BlinQ · Tennis Intelligence</title>\n'
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
    assert "trustedRuntime.dashboard||{}" in app
    assert "trustedRuntime.hero_banner||{}" in app
    assert "if(state.uiStorageAvailable!==true)" in app
    assert "state.runtimeConfigLoaded&&status?.runtime_configured!==true" in app
    automatic = app.split("function loadAdminDraft(){", 1)[1].split(
        "function restoreAdminDraft(){", 1
    )[0]
    assert "mergeConfig" not in automatic
    assert "data-admin-action=\"load-draft\"" in app
    assert "else if(action==='load-draft')restoreAdminDraft()" in app


def test_no_stale_cache_on_spa_alias_and_cms_configs():
    cfg = json.loads((ROOT / "web" / "staticwebapp.config.json").read_text())
    routes = {entry["route"]: entry for entry in cfg["routes"]}
    for route in ("/", "/index.html", "/follow-the-data", "/deployment.json", "/config/*"):
        assert "no-store" in routes[route]["headers"]["Cache-Control"]
    assert routes["/follow-the-data"]["rewrite"] == "/index.html"
    # Azure normalizes the optional trailing slash when validating route rules.
    # A /follow-the-data and /follow-the-data/ pair fails the actual SWA upload.
    normalized = [route.rstrip("/") or "/" for route in routes]
    assert len(normalized) == len(set(normalized)), "Azure rejects duplicate normalized routes"


def test_admin_published_ui_history_is_auth_bound_and_restore_is_preview_only():
    auth = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    storage = (ROOT / "api" / "tbt" / "services" / "admin_storage.py").read_text(encoding="utf-8")
    assert 'async function adminUiSnapshots()' in auth
    assert 'async function adminUiSnapshot(snapshotId)' in auth
    assert 'adminUiSnapshots, adminUiSnapshot' in auth
    assert 'data-admin-action="load-ui-snapshots"' in app
    assert 'data-admin-action="preview-ui-snapshot"' in app
    assert 'function previewAdminUiSnapshot(snapshotId)' in app
    assert 'state.adminPreRestorePreview=current' in app
    assert "const current=clone(state.ui),next=clone(state.ui);" in app
    assert "next.hero_banner=mergeConfig" in app
    assert "marketing.forEach(" in app
    assert "@app.route(route=\"v1/admin/ui-config/snapshots\", methods=[\"GET\"])" in api
    assert "@app.route(route=\"v1/admin/ui-config/snapshots/{snapshot_id}\", methods=[\"GET\"])" in api
    assert api.count("actor, denied = _admin_user(req)") >= 2
    assert "client.create_entity({" in storage
    assert 'previous_snapshot_id' in storage


def test_local_draft_restores_marketing_only_without_reverting_new_entitlements():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'data-admin-action="preview-local-ui-draft"' in app
    assert "function previewLocalAdminUiDraft(){" in app
    assert "function applyAdminPresentationSnapshot(saved){" in app
    presentation = app.split("function applyAdminPresentationSnapshot(saved){", 1)[1].split(
        "async function previewAdminUiSnapshot(snapshotId){", 1
    )[0]
    assert "next.hero_banner=mergeConfig" in presentation
    assert "old.kind!=='hero_banner'" in presentation
    assert "marketing.forEach(" in presentation
    assert "next.dashboard=" not in presentation
    assert "next.access_contract_revision=" not in presentation
    assert "next.notifications=" not in presentation
    assert "if(!state.adminPreRestorePreview)" in presentation
