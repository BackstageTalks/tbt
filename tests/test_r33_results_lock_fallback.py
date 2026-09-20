import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
ENTITLEMENTS = (ROOT / "api" / "tbt" / "services" / "entitlements.py").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_r33_identity_and_cache_revision():
    assert RELEASE["patch"] == UI["ui_patch"] == "736-r33"
    assert 'content="736-r33"' in INDEX
    assert '/app.js?v=7360&p=33' in INDEX
    assert '/blinq-app.css?v=7360&p=33' in INDEX


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
    assert "const p1Photo=p1.photo_url||p1.image_url||p1.photo||'';" in APP
    assert "const p2Photo=p2.photo_url||p2.image_url||p2.photo||'';" in APP


def test_locked_results_navigation_has_lock_and_click_stable_minimum_level_hint():
    assert "access-nav-locked" in APP
    assert "node.dataset.upgradeExplicit='1'" in APP
    assert "route==='results'&&!resultsAccessAllowed()" in APP
    assert "showAccessHint(source,plan,lcopy('Results','Výsledky','Výsledky'),true)" in APP
    assert ".reference-navigation a.access-nav-locked" in CSS


def test_rookie_daily_top_is_stable_random_not_first_two_source_rows():
    rookie = UI["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"]["rookie"]
    assert rookie["visible_rows"] == 2
    assert rookie["selection_mode"] == "stable_random"
