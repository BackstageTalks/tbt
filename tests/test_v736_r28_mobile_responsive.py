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
    assert UI["ui_patch"] == "736-r50"
    assert RELEASE["patch"] == "736-r50"
    assert 'content="736-r50"' in INDEX
    for asset in ("blinq-app.css", "auth.js", "responsive.js", "app.js"):
        assert f"/{asset}?v=7360&p=50" in INDEX
    assert "/assets/blinq_loading_r29.svg?v=7360&p=50" in INDEX


def test_r28_final_mobile_contract_is_last_cascade_layer():
    marker = "BlinQ runtime patch 7.3.6-r28 — mobile-first stability contract"
    # r27 still carried a malformed desktop @media/comment pair. It trapped the
    # runtime visual rules inside min-width:1081px, which is why Telegram/header
    # styling vanished on phones. r28 closes that block before shared rules.
    assert "wrapper swallowed the grid gap{" not in CSS
    assert "placeholder closed so every runtime rule below remains global. */" in CSS
    assert marker in CSS
    tail = CSS[CSS.index(marker):]
    assert "@media (max-width:900px)" in tail
    assert ".reference-topbar .reference-navigation{display:none!important}" in tail
    assert ".daily-tabs{display:flex!important" in tail
    assert "overflow-x:auto!important" in tail
    assert ".daily-hub-table tbody tr:not(.hub-row-locked){display:grid!important" in tail
    assert ".results-table thead{display:none!important}" in tail
    assert ".mobile-tabs a>svg path{fill:none!important" in tail
    assert ".tg-group-icon svg path{fill:currentColor!important" in tail


def test_r28_mobile_cards_use_semantic_labels_not_column_guessing():
    assert "const mobileLabels=dailyHubColumns(tab);" in APP
    assert "cell.dataset.label=mobileLabels[i]||'';" in APP
    tail = CSS[CSS.index("BlinQ runtime patch 7.3.6-r28 — mobile-first stability contract"):]
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
