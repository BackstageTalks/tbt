import json
from pathlib import Path


def test_membership_editors_link_to_single_visibility_panel_without_duplicates():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "function renderAdminDisplayAccess(id)" in app
    assert 'data-admin-display-access="comparator"' not in app  # generated from safe key
    assert "toggle('comparator'" in app
    assert "toggle('results'" in app
    assert "toggle('detail'" in app
    assert "data-admin-display-history" in app
    assert "data-admin-open-level-display" in app
    assert "state.adminTab='layout'" in app
    assert "renderAdminLevelAccess" not in app
    assert "data-admin-level-access" not in app
    assert "data-admin-level-hub-field" not in app
    assert "data-admin-level-history" not in app
    assert "data-admin-results-plan" not in app
    assert "data-admin-detail-plan" not in app
    assert "data-admin-results-window" not in app
    assert "data-admin-detail-section" in app  # global minimum remains editable
    assert "Kontrola neaktivity účtov" in app  # membership lifecycle remains intact


def test_membership_access_remains_draft_only_and_uses_the_same_production_keys():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "if(t.dataset.adminDisplayAccess!==undefined)" in app
    assert "if(t.dataset.adminDisplayHistory!==undefined)" in app
    assert "item.access[id]=t.checked?'active':'locked'" in app
    assert "state.ui.dashboard.results_history_window[id]=value" in app
    assert "cfg.plans[id]=Boolean(t.checked)" in app
    assert "function renderAdminDisplayAccess" in app
    assert "showStatus" in app and "klikni Publikovať" in app



def test_comparator_access_contract_is_shared_frontend_backend():
    web = json.loads(Path("web/ui-config.json").read_text(encoding="utf-8"))
    server = json.loads(Path("api/tbt/assets/ui_access_defaults.json").read_text(encoding="utf-8"))
    expected = {
        "trial": True,
        "expired": False,
        "rookie": True,
        "pro": True,
        "elite": True,
        "legend": True,
        "goat": True,
    }
    assert web["dashboard"]["comparator"]["plans"] == expected
    assert server["dashboard"]["comparator"]["plans"] == expected

    app = Path("web/app.js").read_text(encoding="utf-8")
    api = Path("api/function_app.py").read_text(encoding="utf-8")
    storage = Path("api/tbt/services/admin_storage.py").read_text(encoding="utf-8")

    assert "function comparatorPlanAllowed" in app
    assert "firstComparatorUnlockPlan" in app
    assert "def _comparator_access(" in api
    assert '"comparator_access_required"' in api
    assert 'dashboard.get("comparator")' in storage
    assert "Invalid comparator access for" in storage


def test_rookie_access_edits_keep_trial_alias_in_sync():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "if(id==='rookie')item.access.trial=item.access[id]" in app
    assert "if(id==='rookie')cfg.plans.trial=Boolean(t.checked)" in app
    assert "if(id==='rookie')tc.plans.trial=clone(rule)" in app

# Revalidation marker: merge build must include main 9a312855945987c046b3763246aed4e26f6607d3.
