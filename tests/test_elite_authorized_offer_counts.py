"""Regression contract: ELITE counts and rendered cards use the authorized offer.

The API has already redacted rows; the browser must not reintroduce the
global source total as a member-visible match count or locked placeholder.
LEGEND/GOAT deliberately retain the full-offer presentation.
"""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "web" / "app.js"


def test_elite_daily_tab_count_uses_authorized_rows():
    source = SOURCE.read_text(encoding="utf-8")
    assert "plan==='elite'&&!state.previewPlan?rows.length" in source
    assert "const allCount=plan==='elite'&&!state.previewPlan?rows.length:" in source


def test_elite_daily_table_does_not_render_hidden_global_slots():
    source = SOURCE.read_text(encoding="utf-8")
    assert "if(plan==='elite'&&!state.previewPlan&&!includedButUnavailable)" in source
    assert "rows.slice(0,limit).forEach((row,index)=>out.push(dailyHubRow(row,tab,false,index)))" in source
    assert "if(plan!=='elite'||state.previewPlan)" in source


def test_elite_cards_do_not_count_global_entitlement_total():
    source = SOURCE.read_text(encoding="utf-8")
    assert "const total=accountPlan()==='elite'&&!state.previewPlan?rows.length:" in source
    assert "total=accountPlan()==='elite'&&!state.previewPlan?allRows.length:" in source
