from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
ADMIN_STORAGE = (ROOT / "api" / "tbt" / "services" / "admin_storage.py").read_text(encoding="utf-8")
PUSH = (ROOT / "api" / "tbt" / "services" / "push_notifications.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "live-radar.yml").read_text(encoding="utf-8")
WEB = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def test_autonomous_worker_is_secret_protected_and_publishes():
    assert 'route="v1/internal/live-radar-worker"' in API
    assert 'BLINQ_LIVE_WORKER_TOKEN' in API
    assert 'hmac.compare_digest' in API
    block = API.split('def internal_live_radar_worker(req):', 1)[1].split('@app.route(route="v1/admin/live-radar"', 1)[0]
    assert '_run_live_radar(force=True,publish=True)' in block
    assert 'save_live_worker_status(public)' in block


def test_browser_prefers_worker_snapshot_and_only_falls_back_to_scan():
    block = API.split('def live_radar(req):', 1)[1].split('@app.route(route="v1/internal/live-radar-worker"', 1)[0]
    assert '_live_worker_snapshot()' in block
    assert '"autonomous":True' in block
    assert '_run_live_radar(force=False,publish=True)' in block
    assert '"fallback_scan":True' in block


def test_worker_runs_roughly_once_per_minute_without_browser():
    assert "cron: '*/5 * * * *'" in WORKFLOW
    assert 'for scan in 1 2 3 4 5 6' in WORKFLOW
    assert 'sleep 50' in WORKFLOW
    assert 'X-Blinq-Worker-Token' in WORKFLOW
    assert 'TBT_LIVE_RADAR_ENABLED' in WORKFLOW


def test_worker_heartbeat_is_persistent_and_visible_in_admin_system():
    assert 'def save_live_worker_status' in ADMIN_STORAGE
    assert 'def load_live_worker_status' in ADMIN_STORAGE
    assert 'live-radar-worker-status' in ADMIN_STORAGE
    assert "['LIVE WORKER'" in WEB
    assert 'live_worker_token_missing' in API
    assert 'live_worker_stale' in API


def test_admin_can_receive_same_live_push_as_goat_operational_access():
    # Admin subscriptions are normalized to GOAT operational access, while
    # normal members may subscribe at any active tier and message levels decide delivery.
    push_block = API.split('def push_subscription(req):', 1)[1].split('@app.route(route="v1/insights"', 1)[0]
    assert 'plan = plan if plan in {"elite", "legend", "goat"} else "goat"' in push_block
    assert 'push_status = push_status if push_status in {"active", "lifetime"} else "lifetime"' in push_block
    assert 'plan and plan not in item["levels"]' in ADMIN_STORAGE
    assert '_MEMBERSHIP_LEVELS' in PUSH
    assert 'plan not in levels' in PUSH


def test_worker_skips_provider_when_no_prime_candidate_can_qualify():
    run_block = API.split('def _run_live_radar', 1)[1].split('def _insight_plan_for_user', 1)[0]
    assert 'eligible_pool=[row for row in prime_pool' in run_block
    assert 'if not eligible_pool:' in run_block
    assert 'scan=scan_comeback_radar(feed_payload,[])' in run_block


def test_live_drawer_has_separate_results_tab_for_settled_confirmed_signals():
    assert 'data-live-radar-tab="results"' in WEB
    assert "radar.results" in WEB
    assert "Zatiaľ nie sú vyhodnotené žiadne LIVE signály." in WEB
    assert "settle_radar_results" in API
    assert "list_live_radar_results" in API
