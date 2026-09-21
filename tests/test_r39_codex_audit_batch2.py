from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from tbt.services.feed import visible_feed
from tbt.services.entitlements import (
    blinq_access_day,
    build_daily_access_state,
    filter_feed_for_access,
)

ROOT = Path(__file__).resolve().parents[1]


def row(i: int, when: str):
    return {
        "event_id": f"e{i}",
        "custom_id": f"c{i}",
        "pick": f"P{i}",
        "scheduled_at": when,
        "odds": 1.80,
        "blinq_probability": 0.80 - i / 1000,
        "surface": "hard",
        "player1": {"id": str(100 + i), "name": f"A{i}", "probability": 0.7},
        "player2": {"id": str(200 + i), "name": f"B{i}", "probability": 0.3},
    }


def payload(times):
    rows = [row(i, when) for i, when in enumerate(times)]
    return {
        "generated_at": "2026-09-21T07:00:00+00:00",
        "top_daily_picks": deepcopy(rows),
        "prime_picks": deepcopy(rows),
        "value_picks": deepcopy(rows),
        "doubles_picks": deepcopy(rows),
        "ace_picks": [{**deepcopy(r), "market": "aces"} for r in rows],
        "sg_picks": [{**deepcopy(r), "market": "games"} for r in rows],
        "upcoming": deepcopy(rows),
        "results": [],
    }


def rookie_cfg():
    rule = {
        "visible_rows": 1,
        "blur_remaining": True,
        "tab_enabled": True,
        "see_all": False,
        "selection_mode": "stable_random",
        "display_state": "active",
    }
    return {
        "dashboard": {
            "daily_hub": {
                "enabled": True,
                "tabs": {
                    "daily": {"enabled": True, "plans": {"rookie": deepcopy(rule)}},
                    "prime": {"enabled": True, "plans": {"rookie": deepcopy(rule)}},
                    "value": {"enabled": True, "plans": {"rookie": deepcopy(rule)}},
                },
            }
        }
    }


def test_b09_visible_feed_removes_started_rows_from_every_prematch_array():
    now = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    data = payload([
        "2026-09-21T09:59:00+00:00",
        "2026-09-21T10:01:00+00:00",
    ])
    out = visible_feed(data, now=now)
    for key in ("upcoming", "top_daily_picks", "prime_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks"):
        assert [r["event_id"] for r in out[key]] == ["e1"], key


def test_b11_blinq_access_day_uses_six_am_bratislava_boundary():
    assert blinq_access_day(datetime(2026, 9, 21, 3, 30, tzinfo=timezone.utc)) == "2026-09-20"
    assert blinq_access_day(datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)) == "2026-09-21"


def test_b11_durable_allocation_survives_reorder_append_and_remove_without_new_unlock():
    now = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
    times = [f"2026-09-21T{12 + (i % 8):02d}:00:00+00:00" for i in range(10)]
    base = visible_feed(payload(times), now=now)
    base["value_picks"] = []
    access = {"id": "rookie-1", "status": "active", "plan": "rookie"}
    cfg = rookie_cfg()

    state, changed = build_daily_access_state(access, base, cfg, now=now)
    assert changed is True
    assert len(state["sections"]["daily"]) == 1

    context = {**access, "_daily_allocations": state["sections"], "_access_day": state["day"]}
    first, _ = filter_feed_for_access(base, context, cfg)
    first_id = first["daily_picks"][0]["event_id"]

    changed_feed = deepcopy(base)
    changed_feed["top_daily_picks"] = list(reversed(changed_feed["top_daily_picks"]))
    changed_feed["prime_picks"] = list(reversed(changed_feed["prime_picks"]))
    changed_feed["value_picks"] = list(reversed(changed_feed["value_picks"]))
    changed_feed["top_daily_picks"].append(row(99, "2026-09-21T22:00:00+00:00"))
    changed_feed["prime_picks"].append(row(99, "2026-09-21T22:00:00+00:00"))
    changed_feed["value_picks"].append(row(99, "2026-09-21T22:00:00+00:00"))

    state2, changed2 = build_daily_access_state(
        access,
        changed_feed,
        cfg,
        existing_day=state["day"],
        existing_allocations=state["sections"],
        now=now,
    )
    assert changed2 is False
    assert state2 == state

    context2 = {**access, "_daily_allocations": state2["sections"], "_access_day": state2["day"]}
    second, _ = filter_feed_for_access(changed_feed, context2, cfg)
    assert [r["event_id"] for r in second["daily_picks"]] == [first_id]

    # Removing the assigned row must not grant a replacement pick.
    for key in ("top_daily_picks", "prime_picks", "value_picks"):
        changed_feed[key] = [r for r in changed_feed[key] if r["event_id"] != first_id]
    state3, _ = build_daily_access_state(
        access, changed_feed, cfg,
        existing_day=state["day"], existing_allocations=state["sections"], now=now,
    )
    third, _ = filter_feed_for_access(
        changed_feed,
        {**access, "_daily_allocations": state3["sections"]},
        cfg,
    )
    assert third["daily_picks"] == []


def test_b11_started_assigned_pick_disappears_without_replacement():
    now = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
    times = [f"2026-09-21T{12 + (i % 8):02d}:00:00+00:00" for i in range(10)]
    raw = payload(times)
    base = visible_feed(raw, now=now)
    base["value_picks"] = []
    raw["value_picks"] = []
    access = {"id": "rookie-start", "status": "active", "plan": "rookie"}
    cfg = rookie_cfg()
    state, _ = build_daily_access_state(access, base, cfg, now=now)
    context = {**access, "_daily_allocations": state["sections"]}
    before, _ = filter_feed_for_access(base, context, cfg)
    assigned = before["daily_picks"][0]["event_id"]

    later = datetime(2026, 9, 21, 23, 0, tzinfo=timezone.utc)
    after_visible = visible_feed(raw, now=later)
    state2, _ = build_daily_access_state(
        access, after_visible, cfg,
        existing_day=state["day"], existing_allocations=state["sections"], now=later,
    )
    after, _ = filter_feed_for_access(after_visible, {**access, "_daily_allocations": state2["sections"]}, cfg)
    assert assigned not in {r["event_id"] for r in after["daily_picks"]}
    assert after["daily_picks"] == []


def test_b24_authorized_rows_keep_original_server_slot_identity():
    now = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
    times = [f"2026-09-21T{12 + (i % 8):02d}:00:00+00:00" for i in range(10)]
    base = visible_feed(payload(times), now=now)
    base["value_picks"] = []
    access = {"id": "slot-user", "status": "active", "plan": "rookie"}
    cfg = rookie_cfg()
    state, _ = build_daily_access_state(access, base, cfg, now=now)
    data, manifest = filter_feed_for_access(base, {**access, "_daily_allocations": state["sections"]}, cfg)
    selected = data["daily_picks"][0]
    slot = selected["_access_slot"]
    assert manifest["sections"]["daily"]["slot_states"][slot] == "active"
    assert base["top_daily_picks"][slot]["event_id"] == selected["event_id"]


def test_b24_frontend_uses_server_slot_identity_instead_of_compacting_filtered_rows():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "const bySlot=new Map(),unmapped=[]" in app
    assert "Number(row?._access_slot)" in app
    assert "const row=bySlot.get(slotIndex)??unmapped[dataIndex++]" in app


def test_b24_admin_preview_stable_random_is_not_forced_to_active_prefix():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function previewStableRandomSlots" in app
    assert "randomSlots?randomSlots.has(i):i<visibleCount" in app
