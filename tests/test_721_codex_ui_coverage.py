"""Codex 7.2.1 public TOP visibility contract.

The model/canonical source and member entitlements remain unchanged.
"""
from pathlib import Path
import json


def test_full_top_page_is_not_limited_to_dashboard_preview():
    source = Path("web/app.js").read_text(encoding="utf-8")
    assert "const cap=key==='top_daily'?(Array.isArray(rows)?rows.length:0)" in source
    assert "detailCards(marketRows('top_daily'),'top_daily')" in source
    assert "return `<div class=\"detail-picks-grid\">" in source
    rules = json.loads(Path("web/ui-config.json").read_text(encoding="utf-8"))["market_rules"]["top_daily"]
    assert rules["limit"] is None and rules["target_count"] == 3
    assert rules["presentation_preview_limit"] == 10


def test_significant_duels_use_only_server_authorized_nonbetting_board():
    source = Path("web/app.js").read_text(encoding="utf-8")
    start = source.index("  function renderTop20MatchCoverage(){")
    end = source.index("  function contentLocale(){", start)
    snippet = source[start:end]
    assert "feed.board_upcoming" in snippet
    assert "meta.locked===true" in snippet
    assert "rank>=1&&rank<=20" in snippet
    assert "row.prediction_family!=='doubles'" in snippet
    assert "renderTop20MatchCoverage()" in source[source.index("else if(route==='top_daily')"):]
    assert "marketRows('top_daily')" in snippet
    assert "marketRows('value')" in snippet
    assert "marketRows('prime')" in snippet
    assert ".65" in snippet
    assert "escapeHtml(m.p1)" in snippet and "escapeHtml(m.p2)" in snippet
    assert "No verified model prediction" in snippet
    # This is deliberately never a new bet or client-side odds discovery.
    assert "fetch(" not in snippet and "event_odds(" not in snippet
    assert "return `<section" in snippet


def test_model_feed_eligibility_and_aces_remain_unmodified_by_ui_change():
    source = Path("web/app.js").read_text(encoding="utf-8")
    assert "renderMarketSection('ace','aceGrid'" in source
    assert "renderMarketSection('value','valueGrid'" in source
    assert "renderDailyHub()" in source
    assert "dailyHubRows('daily')" in source
