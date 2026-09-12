from pathlib import Path
import json

from tbt.services.entitlements import entitlement_manifest

ROOT = Path(__file__).resolve().parents[1]


def _rows(n):
    return [
        {
            "event_id": f"e{i}",
            "scheduled_at": f"2026-09-12T{10+i%10:02d}:00:00Z",
            "player1": {"name": f"A{i}", "probability": .72},
            "player2": {"name": f"B{i}", "probability": .28},
            "pick": f"A{i}",
            "odds": 1.60,
        }
        for i in range(n)
    ]


def test_default_daily_hub_access_is_three_ten_all():
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    daily = cfg["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"]
    assert cfg["dashboard"]["daily_hub"]["preview_rows"] == 10
    assert daily["rookie"]["visible_rows"] == 3
    assert daily["rookie"]["see_all"] is False
    assert daily["pro"]["visible_rows"] == 10
    assert daily["pro"]["see_all"] is False
    assert daily["elite"]["visible_rows"] == "ALL"
    assert daily["elite"]["see_all"] is True


def test_server_hard_policy_blocks_expand_before_elite():
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    payload = {"prime_picks": _rows(16), "top_daily_picks": [], "value_picks": [], "ace_picks": [], "sg_picks": []}
    rookie = entitlement_manifest({"status": "active", "plan": "rookie"}, payload, cfg)["sections"]["daily"]
    pro = entitlement_manifest({"status": "active", "plan": "pro"}, payload, cfg)["sections"]["daily"]
    elite = entitlement_manifest({"status": "active", "plan": "elite"}, payload, cfg)["sections"]["daily"]
    assert rookie["visible_picks"] == 3 and rookie["see_all"] is False
    assert pro["visible_picks"] == 10 and pro["see_all"] is False
    assert elite["visible_picks"] == "ALL" and elite["see_all"] is True


def test_frontend_expand_is_entitlement_gated_and_expands_to_all_rows():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "canExpand=ent.see_all===true&&allCount>preview" in app
    assert "limit=(state.dailyHubExpanded&&canExpand)?allCount:preview" in app
    assert "expand.hidden=!canExpand" in app
    assert 'data-admin-hub-field="see_all"' in app
