"""Cleanup regression: removed local helpers are not production entrypoints."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    "visiblePickCount", "dashboardSectionKeyForPanelId", "compactCount",
    "highlightRow", "notificationReadIds", "mergedPrimeRows", "valuePickIds",
    "hubDataDepthLabel", "safeNum", "hubPlayerMeta", "rankMovement",
    "formSequenceHtml", "renderDailyHubInsight", "renderSignal",
    "resultTags", "resultPublication", "genericTable", "adminTelegramLabel",
    "adminTgActionLabel", "loadAdminInfoRetention", "auditDiffLabel",
    "systemState", "renderAdminTraining", "upgradePlanFacts",
)


def test_24_unreferenced_renderers_are_not_reintroduced():
    js = (ROOT / "web/app.js").read_text(encoding="utf-8")
    for name in RETIRED:
        assert not re.search(r"\b(?:async\s+)?function\s+" + name + r"\s*\(", js), name


def test_active_market_admin_and_results_entrypoints_remain():
    js = (ROOT / "web/app.js").read_text(encoding="utf-8")
    for active in (
        "dashboardPreviewLimit", "renderAdminAccounts", "loadAdminInfoResults",
        "renderResults", "adminSystemHealthView", "adminTgAction",
    ):
        assert active in js, active
