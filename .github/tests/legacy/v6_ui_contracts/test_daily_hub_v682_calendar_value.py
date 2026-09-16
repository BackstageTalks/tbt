from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "polish-683.css").read_text(encoding="utf-8")


def test_preview_tab_removed_from_daily_hub():
    render = APP.split("function renderDailyHub(){", 1)[1].split("function marketPreviewCard", 1)[0]
    assert "['daily','top','value','ace','games','doubles','board']" in render
    assert "'calendar'" not in render


def test_daily_hub_is_today_only_and_has_no_date_range_controls():
    assert 'id="dailyHubDateFrom"' not in HTML
    assert 'id="dailyHubDateTo"' not in HTML
    assert 'id="dailyHubDateClear"' not in HTML
    filtered = APP.split("function dashboardFilteredRows(rows){", 1)[1].split("function dailyHubColumns", 1)[0]
    assert "dailyHubDateFrom" not in filtered
    assert "dailyHubDateTo" not in filtered


def test_results_have_custom_date_range_and_preset_switching():
    render = APP.split("function renderResultsFilters(){", 1)[1].split("function settledPublishedEntries", 1)[0]
    wire = APP.split("function wireResultsFilters(){", 1)[1].split("function planSelectOptions", 1)[0]
    assert 'id="resultsDateFrom"' in render
    assert 'id="resultsDateTo"' in render
    assert "['custom',customLabel]" in render
    assert "state.resultsFilters.window='custom'" in wire
    filtered = APP.split("function filteredResults(){", 1)[1].split("function renderResultsFilters", 1)[0]
    assert "filters.window==='custom'" in filtered
    assert "ts<fromTs" in filtered
    assert "ts>toTs" in filtered
    assert ".results-filter-bar-v683" in CSS


def test_value_detail_uses_same_right_rail_detail_as_top():
    wire = APP.split("function wireDailyHub(){", 1)[1].split("function setRoute", 1)[0]
    assert "selectMatchInRail(current,state.dailyHubTab)" in wire
    row_fn = APP.split("function dailyHubRow(row,tab,active=false){", 1)[1].split("function dailyHubLockedRow", 1)[0]
    assert "if(tab==='value')" in row_fn
    assert 'data-hub-detail' in row_fn
    rail = APP.split("function renderSidebarMatchDetail(row=state.railMatch){", 1)[1].split("function renderDashboardSidebar", 1)[0]
    assert "renderRadarComparison(row)" in rail
    assert "renderMatchHistoryPanel(row)" in rail
    assert "data-rail-detail-tab" in rail
