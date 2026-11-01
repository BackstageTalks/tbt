"""Read-only regression contract for the 2026-11-01 BlinQ web access audit.

The API entitlement decides Results access; the local UI matrix is only a
fallback and a configuration editor. No paid provider or CDB call is required.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
UI = json.loads((ROOT / "web/ui-config.json").read_text(encoding="utf-8"))
SERVER = json.loads((ROOT / "api/tbt/assets/ui_access_defaults.json").read_text(encoding="utf-8"))


def test_offline_policy_matches_current_published_member_access():
    results = UI["elements"]["SIDEBAR_RESULTS"]["access"]
    comparator = UI["dashboard"]["comparator"]["plans"]
    assert all(results[p] == "locked" for p in ("trial", "expired", "rookie"))
    assert all(results[p] == "active" for p in ("pro", "elite", "legend", "goat"))
    assert all(comparator[p] is False for p in ("trial", "expired", "rookie", "pro", "elite"))
    assert all(comparator[p] is True for p in ("legend", "goat"))
    assert SERVER["dashboard"]["comparator"]["plans"] == comparator
    # The backend Results fallback intentionally remains conservative without runtime storage.
    server_results = SERVER["elements"]["SIDEBAR_RESULTS"]["access"]
    assert server_results["pro"] == server_results["elite"] == "locked"


def test_comparator_runtime_default_is_not_open_to_rookie():
    api = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    assert '"trial": False, "expired": False, "rookie": False, "pro": False' in api
    assert "const base={plans:{trial:false,expired:false,rookie:false,pro:false,elite:false" in APP


def test_comparator_lock_is_visible_in_both_mobile_navigation_surfaces():
    assert "body#blinqPremium #mobileTabs a.comparator-nav-locked{" in CSS
    assert "body#blinqPremium #mobileTabs a.comparator-nav-locked::after{" in CSS
    assert "body#blinqPremium .mobile-icon-nav a.comparator-nav-locked::after," in CSS


def test_results_server_denial_is_not_an_upgrade_offer():
    assert "resultsServerAccessMismatch()" in APP
    assert "delete node.dataset.upgradePlan;" in APP
    assert "Prístup sa momentálne nepodarilo overiť." in APP
    assert "state.feed?.entitlements?.results" in APP


def test_public_copy_has_targeted_slovak_corrections():
    assert ".replace('Každý zápas ma príbeh','Každý zápas má príbeh')" in APP
    assert ".replace('Staň as súčasťou','Staň sa súčasťou')" in APP
    assert ".replace('s dennym FREE','s denným FREE')" in APP
    assert "Pre zvolené filtre nie sú dostupné vyhodnotené predikcie." in APP


def test_results_access_is_governed_by_server_entitlement_at_runtime():
    """Exercise the real browser access functions with mock entitlement states."""
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    begin = APP.index("  function configuredElementAccess(")
    end = APP.index("  function accessLabel(", begin)
    snippet = APP[begin:end]
    js = """
const vm=require('node:vm');
const assert=require('node:assert/strict');
const snippet=SOURCE;
const c={
  state:{previewPlan:null,ui:{elements:{SIDEBAR_RESULTS:{access:{}}}},feed:{account:{plan:'pro'},entitlements:{}}},
  accessStates:['active','locked','blurred','hidden'],
  elements:()=>c.state.ui.elements,
  accountPlan:()=>c.state.feed.account.plan
};
vm.createContext(c);
vm.runInContext(snippet,c);
const cases=[
  {plan:'pro',ui:'locked',server:true,expected:'active',mismatch:false},
  {plan:'pro',ui:'active',server:false,expected:'locked',mismatch:true},
  {plan:'rookie',ui:'locked',server:false,expected:'locked',mismatch:false},
  {plan:'pro',ui:'active',server:null,expected:'active',mismatch:false},
  {plan:'admin',ui:'locked',server:false,expected:'active',mismatch:false},
];
for(const t of cases){
 c.state.feed.account.plan=t.plan;
 c.state.ui.elements.SIDEBAR_RESULTS.access[t.plan]=t.ui;
 if(t.server===null)delete c.state.feed.entitlements.results;
 else c.state.feed.entitlements.results=t.server;
 assert.equal(c.elementAccess('SIDEBAR_RESULTS'),t.expected,JSON.stringify(t));
 assert.equal(c.resultsServerAccessMismatch(),t.mismatch,JSON.stringify(t));
}
""".replace("SOURCE", json.dumps(snippet, ensure_ascii=False))
    run = subprocess.run(["node", "-e", js], capture_output=True, text=True, cwd=ROOT, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
