"""Guard the opt-in backend feed timing diagnostic against data/access drift."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
AUTH = (ROOT / "web/auth.js").read_text(encoding="utf-8")
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
FEED = API[API.index('@app.route(route="v1/feed", methods=["GET"])'):
           API.index('@app.route(route="v1/internal/clv-snapshot"')]


def test_backend_trace_is_explicit_opt_in_only_after_auth():
    ast.parse(API)  # All existing API routes must remain valid Python.
    assert 'get("blinq_feed_trace") or "") == "1"' in FEED
    assert 'trace_started = time.perf_counter() if trace_requested else None' in FEED
    assert 'if trace_started is not None:' in FEED
    assert 'data["__blinq_feed_stage_ms"] = trace_marks' in FEED
    assert FEED.index('return response({"error": "unauthorized"}, 401)') < FEED.index(
        'trace_stage("auth_verified")')
    assert FEED.index('return response({"error": "email_not_verified"}, 403)') < FEED.index(
        'trace_stage("auth_verified")')
    assert FEED.index('data["__blinq_feed_stage_ms"] = trace_marks') > FEED.index(
        'data = attach_offer_clv(data)')
    assert FEED.endswith('return response({"error": "feed_unavailable"}, 503)\n\n\n')


def test_existing_access_and_feed_workflows_remain_authoritative():
    required = (
        '_verified_user(req)', '_profile_for(user)',
        'public_account(user, cfg=settings, profile=profile)',
        '_visible_issued_feed(_read_feed_with_confirmed_aces_ou())',
        '_feed_support_reads_parallel()', 'apply_result_exclusions',
        'filter_feed_for_access(source_feed, access_context, runtime_ui)',
        'list_project_groups(user_id=str(user.get("id") or ""), include_inactive=False, joined_only=True)',
        'runtime_settled_results', 'filter_results_for_categories',
        'filter_results_for_member_limits', 'filter_results_for_issued_day',
        'apply_verified_schedule_overlay', 'data = attach_offer_clv(data)',
        'return response(data)',
    )
    for token in required:
        assert token in FEED, token
    for stage in (
        "auth_verified", "account_profile", "account_public", "issued_feed",
        "aces_projection", "support_reads", "access_filter",
        "project_groups", "results_kpis", "clv_complete",
    ):
        assert f'trace_stage("{stage}")' in FEED


def test_browser_only_requests_and_displays_trace_when_explicitly_enabled():
    assert "get('blinq_boot_trace') === '1'" in AUTH
    assert "const url = traced ? '/api/v1/feed?blinq_feed_trace=1' : '/api/v1/feed';" in AUTH
    assert "'X-Blinq-Access-Token': s.access_token" in AUTH
    assert "const {timeoutMs = 20000, ...fetchOptions} = options;" in AUTH
    assert 'const feed=(await (pendingFeed||BlinqAuth.feed()))||{};' in APP
    assert "bootTimingProbe?.addBackendStages(feed?.__blinq_feed_stage_ms)" in APP
    assert "if(!enabled)return null;" in APP
    assert "SERVER FEED:" in APP
    assert "sort((a,b)=>b.delta-a.delta).slice(0,6)" in APP


def test_trace_never_shows_payload_or_changes_tennis_loading_screen():
    start = APP.index('// Read-only, opt-in startup timing.')
    end = APP.index('function finishBootSplash(){', start)
    probe = APP[start:end]
    assert "fetch(" not in probe
    assert "localStorage" not in probe
    assert "sessionStorage" not in probe
    assert "innerHTML" not in probe
    assert "performance.now()" in probe
    assert "setTimeout(()=>window.alert(message),450);" in probe
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert 'class="boot-splash boot-splash-tennis"' in html
    assert "/assets/blinq-loader.webp" in html
    assert "/assets/blinq-loader.gif" in html
