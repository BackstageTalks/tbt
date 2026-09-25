from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web/app.js').read_text(encoding='utf-8')
CFG=json.loads((ROOT/'web/ui-config.json').read_text(encoding='utf-8'))


def test_see_all_is_configured_like_a_regular_access_rule():
    see=CFG['dashboard']['daily_hub']['tabs']['see_all']
    assert see['enabled'] is True
    assert see['plans']['rookie']['display_state']=='blurred'
    assert see['plans']['elite']['display_state']=='active'
    assert "if(tab==='see_all')return previewDailyHubEntitlement(tab);" in APP
    assert "tab==='see_all'&&!ent.see_all" not in APP
    assert "data-admin-hub-tab-card=\"${tab}\"" in APP
    assert "if(tab==='see_all')return leanSeeAllRows();" in APP
    assert 'Vyžaduje ELITE' not in APP.split('function dailyHubLockedRow',1)[1].split('function renderDailyHub',1)[0]


def test_row_overrides_are_under_advanced_settings():
    assert 'admin-row-overrides admin-row-advanced' in APP
    assert '>Pokročilé nastavenia<' in APP
    assert 'Riadky 1–10 · SHOW / BLUR / HIDE' in APP


def test_live_minimum_and_info_audiences_are_admin_editable():
    assert CFG['notifications']['live_min_level']=='elite'
    assert CFG['notifications']['info_default_levels']==['rookie','pro','elite','legend','goat']
    for marker in ('adminLiveMinLevel','save-live-access','LIVE PRAVIDLO','LEGEND+','membershipAtLeast'):
        assert marker in APP


def test_admin_remains_unrestricted():
    assert "if(current==='admin')return true;" in APP
    assert "if(String(plan||'').toLowerCase()==='admin')return true;" in APP


def test_locked_rows_and_expand_hints_derive_required_tier_from_config():
    assert "firstDailyHubUnlockPlan(tab,slotIndex,false)" in APP
    assert "firstDailyHubUnlockPlan(state.dailyHubTab,0,true)" in APP
    block=APP.split('function firstDailyHubUnlockPlan',1)[1].split('function dailyHubEntitlement',1)[0]
    assert "row_overrides" in block
    assert "rule.see_all===true" in block
    assert "idx>currentIndex" in block
    assert "currentIndex<0" in block


def test_info_push_can_reach_lower_active_tiers_while_live_stays_dynamic():
    assert "membershipHierarchy.includes(plan)&&['trial','active','lifetime'].includes(status)" in APP


def test_live_runtime_has_no_hardcoded_elite_gate():
    assert "const liveEligible=['elite','legend','goat','admin'].includes(plan)" not in APP
    assert "membershipAtLeast(plan,notificationAudienceConfig().live_min_level)" in APP
