"""Read-only security boundary regression for the production Azure Functions surface.

All routes are HTTP-anonymous at the Azure Functions host layer; authorization
is therefore enforced in the application. A new privileged handler must never
silently be introduced without its server-side guard.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import azure.functions as func
import pytest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api" / "function_app.py"


def _routes():
    tree = ast.parse(API.read_text(encoding="utf-8"), filename=str(API))
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if not (isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "route"):
                continue
            route = next((kw.value.value for kw in decorator.keywords
                          if kw.arg == "route" and isinstance(kw.value, ast.Constant)
                          and isinstance(kw.value.value, str)), None)
            if route:
                yield route, function


def _calls(function):
    return {
        node.func.id: min(
            [other.lineno for other in ast.walk(function)
             if isinstance(other, ast.Call) and isinstance(other.func, ast.Name)
             and other.func.id == node.func.id]
        )
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_all_admin_and_internal_routes_retain_early_server_side_guards():
    privileged = []
    for route, function in _routes():
        if route.startswith("v1/admin/"):
            guards = {"_admin_user"}
        elif route.startswith("v1/internal/"):
            guards = {"_live_worker_token_ok", "_account_worker_token_ok"}
        else:
            continue
        privileged.append(route)
        calls = _calls(function)
        checked = [calls[name] for name in guards if name in calls]
        assert checked, f"{route} has no server-side authorization check"
        assert min(checked) - function.lineno <= 20, (
            f"{route} starts without an early authorization check"
        )
    # A missing file or accidentally disabled scan must never report PASS.
    assert len(privileged) >= 59


def test_admin_guard_is_identity_based_and_suspension_aware():
    tree = ast.parse(API.read_text(encoding="utf-8"))
    guard = next(item for item in tree.body
                 if isinstance(item, ast.FunctionDef) and item.name == "_admin_user")
    calls = _calls(guard)
    assert {"_verified_user", "is_suspended", "is_admin"} <= calls.keys()
    assert calls["_verified_user"] < calls["is_admin"]


def test_firebase_verification_checks_revocation_and_no_admin_email_backdoor():
    source = (ROOT / "api" / "tbt" / "services" / "auth.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    verifier = next(item for item in tree.body
                    if isinstance(item, ast.FunctionDef) and item.name == "_verify_firebase_user")
    verified = [
        call for call in ast.walk(verifier)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and call.func.attr == "verify_id_token"
    ]
    assert len(verified) == 1
    assert any(keyword.arg == "check_revoked"
               and isinstance(keyword.value, ast.Constant)
               and keyword.value.value is True for keyword in verified[0].keywords)
    assert "BLINQ_ADMIN_EMAILS" not in source


def test_frontend_policy_keeps_scripts_same_origin_and_prevents_embedding():
    cfg = json.loads((ROOT / "web" / "staticwebapp.config.json")
                     .read_text(encoding="utf-8"))
    headers = cfg["globalHeaders"]
    csp = headers["Content-Security-Policy"]
    directives = {
        part.split(None, 1)[0]: part.split()[1:]
        for part in csp.split(";") if part.strip()
    }
    assert directives["script-src"] == ["'self'"]
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["base-uri"] == ["'self'"]
    assert directives["form-action"] == ["'self'"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "unsafe-eval" not in csp
    assert "/api/*" in cfg["navigationFallback"]["exclude"]


_PRIVILEGED = [
    (route, handler.name) for route, handler in _routes()
    if route.startswith(("v1/admin/", "v1/internal/"))
]


@pytest.mark.parametrize("route,handler_name", _PRIVILEGED)
def test_privileged_routes_deny_anonymous_without_side_effects(
    monkeypatch, route, handler_name,
):
    """Exercise the actual function handler, not merely its source token names.

    No account, token or expensive provider is available to a caller here. A
    revoked/unauthenticated request cannot reach any protected business logic.
    """
    import function_app as api

    monkeypatch.setattr(api, "_verified_user", lambda req: None)
    monkeypatch.setattr(api, "_live_worker_token_ok", lambda req: False)
    monkeypatch.setattr(api, "_account_worker_token_ok", lambda req: False)
    monkeypatch.setattr(
        api, "RapidTennisClient",
        lambda *args, **kwargs: pytest.fail(
            "Anonymous privileged request attempted a paid provider call"
        ),
    )
    args = {key: "anonymous-probe" for key in re.findall(r"{([^{}]+)}", route)}
    url = "/api/" + re.sub(r"{[^{}]+}", "anonymous-probe", route)
    request = func.HttpRequest(
        method="POST", url="http://localhost" + url,
        headers={}, body=b"{}", route_params=args,
    )
    response = getattr(api, handler_name)(request)
    assert response.status_code in {401, 403, 503}, (
        route, handler_name, response.status_code
    )
    content = response.get_body().decode("utf-8")
    assert "access_token" not in content
    assert "firebase_private_key" not in content


def test_sensitive_route_inventory_is_not_empty():
    assert len(_PRIVILEGED) >= 59
