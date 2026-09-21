import json
from pathlib import Path

from tbt.services.entitlements import filter_feed_for_access

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
ENTITLEMENTS = (ROOT / "api" / "tbt" / "services" / "entitlements.py").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_r33_identity_and_cache_revision():
    assert RELEASE["patch"] == UI["ui_patch"] == "736-r49"
    assert 'content="736-r49"' in INDEX
    assert '/app.js?v=7360&p=49' in INDEX
    assert '/blinq-app.css?v=7360&p=49' in INDEX


def test_results_are_filtered_to_real_blinq_public_categories_client_and_server():
    assert "const publicResultSections=new Set(['top_daily','prime','value','doubles','ace','double_faults','sets','games'])" in APP
    assert "function publicResultPublications(row)" in APP
    assert "const pubs=publicResultPublications(row);" in APP
    assert 'PUBLIC_RESULT_SECTIONS = {"top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}' in ENTITLEMENTS
    assert "def _public_result_publications(row: dict)" in ENTITLEMENTS
    assert 'copy["market_publications"] = publications' in ENTITLEMENTS


def test_results_player_photo_falls_directly_to_repo_fallback_when_history_has_no_photo():
    assert "/assets/missing_foto_m.webp" in APP
    assert "/assets/missing_foto_w.webp" in APP
    assert "Historical result rows frequently do not carry a verified player photo." in APP
    assert "const p1Photo=playerPhotoSource(r,p1,'player1');" in APP
    assert "const p2Photo=playerPhotoSource(r,p2,'player2');" in APP


def test_locked_results_navigation_has_lock_and_click_stable_minimum_level_hint():
    assert "access-nav-locked" in APP
    assert "node.dataset.upgradeExplicit='1'" in APP
    assert "route==='results'&&!resultsAccessAllowed()" in APP
    assert "showAccessHint(source,plan,lcopy('Results','Výsledky','Výsledky'),true)" in APP
    assert ".reference-navigation a.access-nav-locked" in CSS


def test_rookie_core_three_are_one_stable_random_each():
    daily = UI["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"]["rookie"]
    prime = UI["dashboard"]["daily_hub"]["tabs"]["prime"]["plans"]["rookie"]
    assert daily["visible_rows"] == 1
    assert daily["selection_mode"] == "stable_random"
    assert prime["visible_rows"] == 1
    assert prime["selection_mode"] == "stable_random"
    value = UI["dashboard"]["daily_hub"]["tabs"]["value"]["plans"]["rookie"]
    assert value["visible_rows"] == 1
    assert value["selection_mode"] == "stable_random"


def test_old_runtime_config_is_migrated_to_rookie_short_odds_stable_random():
    cfg = json.loads(json.dumps(UI))
    cfg["ui_patch"] = "736-r32"
    cfg["dashboard"]["daily_hub"]["tabs"]["prime"]["plans"]["rookie"]["selection_mode"] = "first"
    rows = []
    for i in range(4):
        rows.append({
            "event_id": f"prime-{i}",
            "scheduled_at": f"2026-09-20T1{i}:00:00Z",
            "tour": "ATP",
            "player1": {"id": f"a{i}", "name": f"A{i}", "probability": .8},
            "player2": {"id": f"b{i}", "name": f"B{i}", "probability": .2},
            "betting": {"odds": 1.25},
        })
    payload = {
        "prime_picks": rows,
        "top_daily_picks": [], "value_picks": [], "doubles_picks": [],
        "ace_picks": [], "sg_picks": [], "upcoming": rows, "results": [],
    }
    _, manifest = filter_feed_for_access(
        payload, {"status": "active", "plan": "rookie", "id": "r33-rookie"}, cfg
    )
    assert manifest["sections"]["prime"]["visible_picks"] == 1
    assert manifest["sections"]["prime"]["selection_mode"] == "stable_random"


def test_rookie_random_sampling_survives_missing_runtime_ui_config():
    rows = []
    for i in range(5):
        rows.append({
            "event_id": f"fallback-prime-{i}",
            "scheduled_at": f"2026-09-20T1{i}:00:00Z",
            "tour": "ATP",
            "player1": {"id": f"a{i}", "name": f"A{i}", "probability": .8},
            "player2": {"id": f"b{i}", "name": f"B{i}", "probability": .2},
            "betting": {"odds": 1.25},
        })
    payload = {
        "prime_picks": rows,
        "top_daily_picks": [], "value_picks": [], "doubles_picks": [],
        "ace_picks": [], "sg_picks": [], "upcoming": rows, "results": [],
    }
    _, manifest = filter_feed_for_access(
        payload, {"status": "active", "plan": "rookie", "id": "no-runtime"}, None
    )
    assert manifest["sections"]["prime"]["selection_mode"] == "stable_random"
    assert manifest["sections"]["prime"]["returned"] == 1
