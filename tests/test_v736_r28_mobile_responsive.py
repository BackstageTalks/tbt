from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
APP = (WEB / "app.js").read_text(encoding="utf-8")
RESPONSIVE = (WEB / "responsive.js").read_text(encoding="utf-8")
CSS = (WEB / "blinq-app.css").read_text(encoding="utf-8")
UI = json.loads((WEB / "ui-config.json").read_text(encoding="utf-8"))
RELEASE = json.loads((WEB / "release.json").read_text(encoding="utf-8"))


def test_r28_release_and_cache_identity():
    assert UI["ui_patch"] == "736-r61"
    assert RELEASE["patch"] == "736-r61"
    assert 'content="736-r61"' in INDEX
    for asset in ("blinq-app.css", "auth.js", "responsive.js", "app.js"):
        assert f"/{asset}?v=7360&p=61" in INDEX
    assert "/assets/blinq-loader.gif?v=7360&p=61" in INDEX


def test_r28_final_mobile_contract_is_last_cascade_layer():
    marker = "BlinQ mobile application shell — 2026-10-02"
    assert marker in CSS
    tail = CSS[CSS.index(marker):]
    assert "@media (max-width:767px)" in tail
    assert "@media (min-width:768px) and (max-width:900px)" in tail
    assert "grid-template-areas:\"brand actions\"" in tail
    assert ".project-group-bar{display:none!important}" in tail
    assert "width:44px" in tail
    assert "#03110f" in tail.lower()
    assert "#08201b" in tail.lower()
    assert "#20463b" in tail.lower()
    assert "#24e8ac" in tail.lower()
    assert ".results-filter-shell.is-open .results-filter-bar.results-filter-bar-v683{display:grid}" in tail
    assert ".results-outcome-tabs" in tail
    assert ".results-table tbody tr.results-card-row" in tail
    assert ".daily-hub-table tbody tr:not(.hub-row-locked)" in tail

def test_r28_mobile_cards_use_semantic_labels_not_column_guessing():
    assert "const mobileLabels=dailyHubColumns(tab);" in APP
    assert "cell.dataset.label=mobileLabels[i]||'';" in APP
    tail = CSS[CSS.index("BlinQ mobile application shell — 2026-10-02"):]
    for cls in ("hub-rank", "hub-time", "hub-tournament-cell", "hub-match-cell", "hub-pick", "hub-odds", "hub-confidence-cell", "hub-action-cell"):
        assert f".{cls}" in tail


def test_r28_mobile_viewport_tracks_visual_keyboard_and_safe_height():
    assert "function syncViewportState()" in RESPONSIVE
    assert "--bq-viewport-height" in RESPONSIVE
    assert "blinq-mobile-layout" in RESPONSIVE
    assert "blinq-mobile-keyboard-open" in RESPONSIVE
    assert "window.visualViewport?.addEventListener('resize',syncViewportState" in RESPONSIVE


def test_r28_hero_is_responsive_and_non_primary_slides_are_lazy():
    assert 'media="(max-width: 900px)"' in APP
    assert "loading=\"${first?'eager':'lazy'}\"" in APP
    assert "fetchpriority=\"high\"" in APP


def test_mobile_web_shell_keeps_desktop_data_and_apps_up_only_the_phone_layout():
    assert "results-filter-shell" in APP
    assert "results-mobile-filter-toggle" in APP
    assert "resultsFilterApply" in APP
    assert "resultsFilterReset" in APP
    assert "results-card-row" in APP
    assert "data-results-filter-toggle" in APP
    assert "mobile-web-shell=3" in INDEX
    assert "const staged=window.matchMedia('(max-width:767px)').matches;" in APP
    assert "phoneOutcome=window.matchMedia('(max-width:767px)').matches" in APP
    marker = "BlinQ mobile application shell — 2026-10-02"
    assert marker in CSS
    tail = CSS[CSS.index(marker):]
    assert "@media (max-width:767px)" in tail
    assert "@media (min-width:768px) and (max-width:900px)" in tail
    assert 'grid-template-areas:"brand actions"' in tail
    assert '.project-group-bar{display:none!important}' in tail
    assert '.results-filter-actions' in tail
    assert '.results-table tbody tr.results-card-row' in tail
    assert '.mobile-tabs' in tail
