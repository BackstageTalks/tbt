import json
from pathlib import Path

from tbt.services.admin_storage import validate_ui_config

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "blinq-app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
FUNCTION_APP = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
UI = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def test_r31_release_and_footer_live_heartbeat_contract():
    assert UI["ui_patch"] == "736-r44"
    assert 'content="736-r44"' in INDEX
    assert 'id="footerSystemStatus"' in INDEX
    assert "Všetky systémy funkčné" in INDEX
    assert 'id="footerLastUpdate">Aktualizácia modelu: —' in INDEX
    assert "function renderSystemFooterStatus()" in APP
    assert "`Aktualizácia modelu: ${fmtTime(raw)}`" in APP
    assert "state.liveRadarHeartbeat=data?.live_radar_status" in APP
    assert 'payload["live_radar_status"] = _public_live_worker_heartbeat()' in FUNCTION_APP
    assert '"fresh": fresh' in FUNCTION_APP
    assert "age_seconds<=180" in FUNCTION_APP
    assert 'snapshot.get("last_success_at")' in FUNCTION_APP
    assert 'if not snapshot or snapshot.get("last_error")' in FUNCTION_APP


def test_r31_status_dot_breathes_and_active_market_tab_has_no_dot_marker():
    assert "@keyframes blinqStatusBreath" in CSS
    assert "animation:blinqStatusBreath" in CSS
    assert ".daily-hub-tab.active .daily-hub-tab-copy>span::before{content:none!important" in CSS
    assert ".daily-hub-tab.active::after" in CSS


def test_r31_visual_cleanup_removes_model_board_toggle_and_tg_mark_from_runtime_markup():
    assert "dailyHubBoardNotice" not in INDEX
    assert 'data-board-mode="live"' not in INDEX
    assert 'data-board-mode="results"' not in INDEX
    assert "tg-panel-mark" not in APP
    assert "windowNote" not in APP
    assert "boardMode:" not in APP


def test_r31_match_detail_tier_config_is_valid_and_admin_editable():
    detail = UI["dashboard"]["match_detail"]
    assert detail["plans"]["rookie"] is True
    assert detail["plans"]["goat"] is True
    assert detail["sections"] == {
        "overview": "rookie",
        "statistics": "pro",
        "radar": "elite",
        "history": "legend",
    }
    assert validate_ui_config(UI) is UI
    assert 'data-admin-detail-plan="${escapeHtml(id)}"' in APP
    assert 'data-admin-detail-section="${escapeHtml(section)}"' in APP
    assert "Dostupné od: ${required}" in APP


def test_r31_match_detail_has_section_locks_and_no_status_meta_footer():
    start = APP.index("function matchDetailHtml")
    end = APP.index("function openMatchPopout", start)
    block = APP[start:end]
    assert "matchDetailSectionAllowed('statistics')" in block
    assert "matchDetailSectionAllowed('radar')" in block
    assert "matchDetailSectionAllowed('history')" in block
    assert "matchDetailLockHtml" in block
    assert "dialog-meta" not in block
    assert "dialog-system-ok" not in block
    assert "Match detail keeps the established r30 visual language" in CSS
    assert "Preserve the established detail-card visual; improve only lower-panel readability." in CSS


def test_results_default_to_legend_plus_and_keep_admin_visibility_toggle():
    entitlements = (ROOT / "api" / "tbt" / "services" / "entitlements.py").read_text(encoding="utf-8")
    assert '"rookie": 0' in entitlements
    assert '"pro": 0' in entitlements
    assert '"elite": 0' in entitlements
    assert '"legend": None' in entitlements
    block = APP[APP.index("function resultsHistoryHours"):APP.index("function renderResultsFilters")]
    assert "results_history_hours" in block
    assert 'data-admin-results-plan="${escapeHtml(id)}"' in APP
    assert "SIDEBAR_RESULTS" in APP
    assert 'data-ui-element="SIDEBAR_RESULTS"' in INDEX


def test_r31_rolling_performance_is_only_rendered_as_single_model_success_kpi():
    engine = (ROOT / "api" / "tbt" / "services" / "engine.py").read_text(encoding="utf-8")
    assert 'PERFORMANCE_WINDOWS_DAYS = (3, 7, 10, 14, 30)' in engine
    assert 'best_accuracy_min_sample' in engine
    assert '"dashboard_model_success"' in engine
    assert 'dashboardBest=state.feed?.dashboard_model_success' in APP
    assert 'dailyHubPerformanceText' not in APP
    assert 'market-card-performance' not in APP
    assert 'Najlepšie z 3/7/10/14/30d' not in APP
