"""ELITE retains server-authorized counts and redacted, ordered positions.

The API never sends locked pick details. The UI may display the original slot
numbers and a locked teaser, but must not synthesize extra pick records.
"""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "web" / "app.js"


def test_elite_counts_remain_authorized_only():
    source = SOURCE.read_text(encoding="utf-8")
    assert "plan==='elite'&&!state.previewPlan?rows.length" in source
    assert "const allCount=plan==='elite'&&!state.previewPlan?rows.length:" in source
    assert "const total=accountPlan()==='elite'&&!state.previewPlan?rows.length:" in source
    assert "total=accountPlan()==='elite'&&!state.previewPlan?allRows.length:" in source


def test_elite_uses_original_server_slot_positions_with_redacted_locks():
    source = SOURCE.read_text(encoding="utf-8")
    assert "if(slotStates.length&&!includedButUnavailable)" in source
    assert "const raw=Number(row?._access_slot);" in source
    assert "slotStates.slice(0,limit).forEach((slotState,slotIndex)=>{" in source
    assert "const eliteTeaser=plan==='elite'&&!explicitlyHidden&&slotState==='hidden';" in source
    assert "if(slotState==='hidden'&&!eliteTeaser)return;" in source
    assert "out.push(dailyHubLockedRow(tab,slotIndex,firstDailyHubUnlockPlan(tab,slotIndex,false)));" in source
    assert "if(row)out.push(dailyHubRow(row,tab,false,slotIndex));" in source
    assert 'class="hub-locked-rank"' in source
    assert "rows.slice(0,limit).forEach((row,index)=>out.push(dailyHubRow(row,tab,false,index)))" not in source


def test_elite_locked_tab_can_show_teasers_but_lock_action_still_upgrades():
    source = SOURCE.read_text(encoding="utf-8")
    assert "if(tab.dataset.upgradePlan&&accountPlan()!=='elite')" in source
    assert "target.closest('tr.hub-row-locked[data-upgrade-plan]')" in source
    assert "showAccessHint(lockedRow,lockedRow.dataset.upgradePlan" in source
    assert "String(ent.row_overrides?.[String(slotIndex+1)]||'').toLowerCase()==='hidden'" in source
