"""AUD-15: every Azure route is classified and its guard runs before other work.

Host-level auth is ANONYMOUS, so the application guard is the only barrier.
A new route fails this test until it is added to the matrix below.
"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "api" / "function_app.py"

WORKER_GUARDS = {"_live_worker_token_ok", "_account_worker_token_ok"}
ADMIN_GUARDS = {"_admin_user"}

# Non-internal, non-admin routes: explicit expected guard, or "public".
OTHER = {
    "health": "public",
    "v1/auth/config": "public",
    "v1/ui-config": "public",
    "v1/content/news": "public",
    "v1/banner-events": "public",
    "v1/media/{media_id}": "public",
    "v1/player-image/{player_id}": "public",
    "v1/tournament-logo/{tournament_id}": "public",
    "v1/account/reactivate-free": "auth_reactivate_free",
    "v1/feed": "_authorized_feed_payload",
    "v1/results": "_authorized_results_payload",
    "v1/brackets": "_verified_user",
    "v1/comparator/players": "_comparator_user",
    "v1/comparator/compare": "_comparator_user",
    "v1/insights/media/{media_id}": "_admin_user|_verified_user",
    "v1/auth/email": "_verified_user",
    "v1/auth/me": "_verified_user",
    "v1/auth/free": "_verified_user",
    "v1/auth/profile": "_verified_user",
    "v1/match-intelligence": "_verified_user",
    "v1/live-radar": "_verified_user",
    "v1/push/config": "_verified_user",
    "v1/push/subscription": "_verified_user",
    "v1/project-groups": "_verified_user",
    "v1/project-groups/{group_id}/join": "_verified_user",
    "v1/insights": "_verified_user",
    "v1/insights/{insight_id}/read": "_verified_user",
    "v1/telemetry/page-reload": "_verified_user",
}

# Calls allowed before the guard: pure request parsing / response helpers.
PRE_GUARD_OK = {"response", "get", "upper", "lower", "strip", "str", "len",
                "dict", "getattr", "isinstance", "bool", "int", "_method",
                "get_json", "max", "min", "float", "list", "set", "split",
                "fullmatch", "getenv"}


def _routes():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "route":
                route = next(k.value.value for k in dec.keywords if k.arg == "route")
                yield route, fn


def _calls(fn):
    out = []
    for node in (n for stmt in fn.body for n in ast.walk(stmt)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name:
                out.append((node.lineno, node.col_offset, name))
    return [n for _, _, n in sorted(out)]


def _guard_first(fn, guards):
    for name in _calls(fn):
        if name in guards:
            return True
        if name not in PRE_GUARD_OK:
            return False
    return False


def test_every_route_is_classified_and_guarded_first():
    problems, seen = [], set()
    for route, fn in _routes():
        seen.add(route)
        if route.startswith("v1/internal/"):
            ok = _guard_first(fn, WORKER_GUARDS)
        elif route.startswith("v1/admin/"):
            ok = _guard_first(fn, ADMIN_GUARDS)
        elif route not in OTHER:
            problems.append(route + ": unclassified route (add to OTHER)")
            continue
        elif OTHER[route] == "public":
            ok = True
        else:
            ok = _guard_first(fn, set(OTHER[route].split("|")))
        if not ok:
            problems.append(route + ": guard is not the first effective call")
    stale = set(OTHER) - seen
    assert not stale, sorted(stale)
    assert not problems, problems
