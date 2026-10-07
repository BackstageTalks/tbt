import json
from pathlib import Path


def test_admin_membership_cards_expose_real_access_controls():
    app = Path("web/app.js").read_text(encoding="utf-8")
    assert "function renderAdminLevelAccess" in app
    assert 'data-admin-level-access="comparator"' in app
    assert 'data-admin-level-access="results"' in app
    assert 'data-admin-level-access="detail"' in app
    assert "data-admin-level-history" in app
    assert "data-admin-level-hub-field" in app
    assert "Rýchle nastavenia používajú rovnaké pravidlá ako Zobrazenie" in app


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
