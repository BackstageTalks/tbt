"""Regression: ELITE's aggregate paywall and VIAC ES exclusion are independent."""
import copy
import json
from pathlib import Path

from tbt.services.admin_storage import resolve_ui_access_config, ui_config_revision
from tbt.services.entitlements import filter_feed_for_access

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))


def _input(n=81):
    rows = [
        {
            "event_id": f"more-aces-{i}", "market": "most_aces",
            "scheduled_at": "2026-11-10T19:00:00Z", "surface": "hard",
            "selection_id": f"alpha-{i}", "pick": "Alpha",
            "player1": {"id": f"alpha-{i}", "name": "Alpha", "probability": 0.75},
            "player2": {"id": f"beta-{i}", "name": "Beta", "probability": 0.25},
        }
        for i in range(n)
    ]
    rows += [
        {
            "event_id": "aces-allowed", "market": "aces", "surface": "hard",
            "scheduled_at": "2026-11-10T19:00:00Z", "pick": "Alpha",
            "player1": {"id": "alpha", "name": "Alpha", "probability": 0.75},
            "player2": {"id": "beta", "name": "Beta", "probability": 0.25},
        }
    ]
    return {
        "ace_picks": rows, "daily_picks": [], "prime_picks": [],
        "top_daily_picks": [], "value_picks": [], "doubles_picks": [],
        "sg_picks": [], "upcoming": [], "results": [],
    }


def test_existing_azure_three_picks_and_unlocked_aggregate_migrate_once():
    old = copy.deepcopy(BASE)
    old["elite_ace_winner_access_revision"] = 1
    old.pop("elite_see_all_lock_revision", None)
    tabs = old["dashboard"]["daily_hub"]["tabs"]
    tabs["ace_winner"]["plans"]["elite"].update({
        "visible_rows": 3, "blur_remaining": False, "display_state": "active",
        "row_overrides": {"8": "active"},
    })
    tabs["see_all"]["plans"]["elite"].update({
        "visible_rows": "ALL", "see_all": True, "blur_remaining": False,
        "display_state": "active", "row_overrides": {"5": "active"},
    })
    original = copy.deepcopy(old)
    effective = resolve_ui_access_config(old)
    assert old == original  # pure read-side correction: never mutate stored row
    assert ui_config_revision(old) != ui_config_revision(effective)
    assert effective["elite_ace_winner_access_revision"] == 2
    assert effective["elite_see_all_lock_revision"] == 1
    for tab in ("see_all", "ace_winner"):
        rule = effective["dashboard"]["daily_hub"]["tabs"][tab]["plans"]["elite"]
        assert rule["visible_rows"] == 0
        assert rule["blur_remaining"] is True
        assert rule["display_state"] == "blurred"
        assert rule["see_all"] is False
        assert rule["row_overrides"] == {}
    for tab in ("see_all", "ace_winner"):
        assert effective["dashboard"]["daily_hub"]["tabs"][tab]["plans"]["legend"] == old["dashboard"]["daily_hub"]["tabs"][tab]["plans"]["legend"]
        assert effective["dashboard"]["daily_hub"]["tabs"][tab]["plans"]["goat"] == old["dashboard"]["daily_hub"]["tabs"][tab]["plans"]["goat"]
    assert effective["dashboard"]["daily_hub"]["tabs"]["ace"] == old["dashboard"]["daily_hub"]["tabs"]["ace"]

    # Once published with both markers, future deliberate Admin choices win.
    effective["dashboard"]["daily_hub"]["tabs"]["see_all"]["plans"]["elite"]["display_state"] = "active"
    effective["dashboard"]["daily_hub"]["tabs"]["ace_winner"]["plans"]["elite"]["visible_rows"] = 1
    again = resolve_ui_access_config(effective)
    assert again["dashboard"]["daily_hub"]["tabs"]["see_all"]["plans"]["elite"]["display_state"] == "active"
    assert again["dashboard"]["daily_hub"]["tabs"]["ace_winner"]["plans"]["elite"]["visible_rows"] == 1


def test_elite_gets_no_more_aces_payload_or_results_grant_but_keeps_aces():
    config = resolve_ui_access_config(BASE)
    original = _input()
    frozen = copy.deepcopy(original)
    elite, ent = filter_feed_for_access(original, {"plan": "elite", "status": "active", "id": "elite-1"}, config)
    assert original == frozen  # redaction never mutates immutable issuance source
    assert ent["sections"]["see_all"]["display_state"] == "blurred"
    assert ent["sections"]["see_all"]["visible_picks"] == 0
    assert ent["sections"]["ace_winner"]["total"] == 81
    assert ent["sections"]["ace_winner"]["returned"] == 0
    assert ent["sections"]["ace_winner"]["display_state"] == "blurred"
    assert "ace_winner" not in ent["result_categories"]
    assert not [r for r in elite["ace_picks"] if r.get("market") == "most_aces"]
    assert [r for r in elite["ace_picks"] if r.get("market") == "aces"]

    legend, upper = filter_feed_for_access(original, {"plan": "legend", "status": "active", "id": "legend-1"}, config)
    assert upper["sections"]["see_all"]["display_state"] == "active"
    assert upper["sections"]["ace_winner"]["returned"] == 81
    assert len([r for r in legend["ace_picks"] if r.get("market") == "most_aces"]) == 81
    assert len(original["ace_picks"]) == 82  # no mutation of raw offer/ledger


def test_mobile_and_desktop_see_all_read_server_entitlement_not_local_guess():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "state.feed?.entitlements?.sections?.see_all||previewDailyHubEntitlement(tab)" in app
    assert "rule.enabled===false||rule.tab_enabled===false||display!=='active'" in app
    assert "dailyHubLockedRow(tab,0,firstDailyHubUnlockPlan(tab,0,tab==='see_all'))" in app
    assert "if(tab==='see_all')return leanSeeAllRows();" not in app
