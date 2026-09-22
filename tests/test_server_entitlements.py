from datetime import datetime, timezone

from tbt.services.entitlements import build_daily_access_state, filter_feed_for_access, effective_plan


def row(i):
    return {"event_id": str(i), "winner_id": "a", "signals": ["x"], "betting": {"odds": 2.0},
            "player1": {"id": "a", "name": "A", "probability": .7},
            "player2": {"id": "b", "name": "B", "probability": .3}}


def feed(n=8):
    # Public market-selection output is disjoint across Value/TOP. Keep the
    # entitlement fixture realistic so the canonical TOP alias is exercised.
    payload = {
        "prime_picks": [row(100 + i) for i in range(n)],
        "top_daily_picks": [row(i) for i in range(n)],
        "value_picks": [row(200 + i) for i in range(n)],
        "doubles_picks": [row(300 + i) for i in range(n)],
        "ace_picks": [row(400 + i) for i in range(n)],
        "sg_picks": [row(500 + i) for i in range(n)],
    }
    payload["upcoming"] = [row(i) for i in range(n)]
    payload["results"] = []
    return payload


def test_suspended_is_denied():
    try:
        filter_feed_for_access(feed(), {"status": "suspended", "plan": "pro"})
    except PermissionError:
        pass
    else:
        raise AssertionError("suspended account must be denied")


def test_rookie_never_receives_hidden_rows():
    data, manifest = filter_feed_for_access(feed(), {"status": "active", "plan": "rookie"})
    assert len(data["prime_picks"]) == 1
    assert len(data["top_daily_picks"]) == 1
    assert len(data["value_picks"]) == 1
    assert len(data["ace_picks"]) == 0
    assert len(data["doubles_picks"]) == 0
    assert len(data["sg_picks"]) == 0
    assert manifest["sections"]["prime"]["enabled"] is True


def test_trial_inherits_rookie_server_side():
    assert effective_plan({"status": "trial", "plan": "rookie"}) == "rookie"


def test_expired_has_only_explicit_free_subset():
    data, _ = filter_feed_for_access(feed(), {"status": "expired", "plan": "expired"})
    assert len(data["prime_picks"]) == 0
    assert len(data["top_daily_picks"]) == 0
    assert len(data["ace_picks"]) == 0


def test_elite_gets_full_curated_feed():
    data, _ = filter_feed_for_access(feed(), {"status": "active", "plan": "elite"})
    assert len(data["prime_picks"]) == 8
    assert len(data["sg_picks"]) == 8


def test_admin_runtime_can_set_zero_to_ten_rows_per_category():
    cfg = {
        "dashboard": {
            "daily_hub": {
                "enabled": True,
                "tabs": {
                    "prime": {"enabled": True, "plans": {"rookie": {"visible_rows": 7, "blur_remaining": True, "tab_enabled": True, "see_all": False}}},
                    "daily": {"enabled": True, "plans": {"rookie": {"visible_rows": 10, "blur_remaining": True, "tab_enabled": True, "see_all": False}}},
                    "value": {"enabled": True, "plans": {"rookie": {"visible_rows": 4, "blur_remaining": True, "tab_enabled": True, "see_all": False}}},
                    "doubles": {"enabled": True, "plans": {"rookie": {"visible_rows": 6, "blur_remaining": True, "tab_enabled": True, "see_all": False}}},
                    "ace": {"enabled": True, "plans": {"rookie": {"visible_rows": 5, "blur_remaining": True, "tab_enabled": True, "see_all": False}}},
                    "games": {"enabled": True, "plans": {"rookie": {"visible_rows": 2, "blur_remaining": True, "tab_enabled": True, "see_all": False}}},
                },
            }
        }
    }
    data, manifest = filter_feed_for_access(feed(12), {"status": "active", "plan": "rookie"}, cfg)
    assert len(data["prime_picks"]) == 7
    assert len(data["top_daily_picks"]) == 10
    assert len(data["value_picks"]) == 4
    assert len(data["doubles_picks"]) == 6
    assert len(data["ace_picks"]) == 5
    assert len(data["sg_picks"]) == 2
    assert manifest["sections"]["prime"]["see_all"] is False


def board_row(i=1, *, probability=.68, depth=.90, p1_surface=12, p2_surface=11, odds=None):
    item = row(i)
    item.update({
        "surface": "hard",
        "blinq_probability": probability,
        "data_depth": depth,
        "quality": {
            "player1": {"surface_matches": p1_surface},
            "player2": {"surface_matches": p2_surface},
        },
    })
    if odds is None:
        item.pop("odds", None)
        item["betting"] = {}
    else:
        item["odds"] = odds
        item["betting"] = {"odds": odds}
    return item


def test_blinq_board_is_legend_goat_admin_only_and_does_not_require_odds():
    payload = feed(0)
    payload["upcoming"] = [
        board_row(1, probability=.68, odds=None),
        board_row(2, probability=.64, odds=1.8),
        board_row(3, probability=.71, depth=.79, odds=2.1),
        board_row(4, probability=.72, p1_surface=4, odds=1.3),
    ]
    for plan in ("rookie", "pro", "elite"):
        data, manifest = filter_feed_for_access(payload, {"status": "active", "plan": plan})
        assert data["board_upcoming"] == []
        assert manifest["sections"]["board"]["enabled"] is False
    for plan in ("legend", "goat"):
        data, manifest = filter_feed_for_access(payload, {"status": "active", "plan": plan})
        assert [item["event_id"] for item in data["board_upcoming"]] == ["1"]
        assert data["board_upcoming"][0].get("odds") is None
        assert data["board_meta"]["official_prediction"] is False
        assert manifest["sections"]["board"]["official_prediction"] is False


def test_blinq_board_results_are_separate_from_official_results():
    payload = feed(0)
    settled = board_row(9, probability=.70, odds=None)
    settled["result"] = {"correct": True, "status": "settled"}
    payload["results"] = [settled]
    data, _ = filter_feed_for_access(payload, {"status": "active", "plan": "legend"})
    assert len(data["board_results"]) == 1
    assert data["board_results"][0]["event_id"] == "9"
    # Board owns a derived view. An unclassified Board-only row must not leak
    # into the official BlinQ Results categories.
    assert data["results"] == []


def test_aces_and_double_faults_have_independent_server_entitlements():
    payload = feed(0)
    payload["ace_picks"] = [
        {**row(1), "market": "aces", "selection_id": "a1"},
        {**row(2), "market": "aces", "selection_id": "a2"},
        {**row(3), "market": "double_faults", "selection_id": "d1"},
        {**row(4), "market": "double_faults", "selection_id": "d2"},
    ]
    cfg = {
        "dashboard": {"daily_hub": {"tabs": {
            "ace": {"enabled": True, "plans": {"pro": {
                "visible_rows": 1, "blur_remaining": True, "tab_enabled": True,
                "see_all": False, "selection_mode": "first", "display_state": "active",
            }}},
            "double_faults": {"enabled": True, "plans": {"pro": {
                "visible_rows": 2, "blur_remaining": True, "tab_enabled": True,
                "see_all": False, "selection_mode": "first", "display_state": "active",
            }}},
        }}}
    }

    data, manifest = filter_feed_for_access(
        payload, {"status": "active", "plan": "pro", "uid": "u"}, cfg,
    )

    assert [item["market"] for item in data["ace_picks"]] == ["aces", "double_faults", "double_faults"]
    assert manifest["sections"]["ace"]["returned"] == 1
    assert manifest["sections"]["double_faults"]["returned"] == 2


def test_stable_random_unlocks_positions_in_place_instead_of_moving_picks_to_top():
    cfg = {
        "dashboard": {"daily_hub": {"enabled": True, "tabs": {
            "prime": {"enabled": True, "plans": {"rookie": {
                "visible_rows": 1, "blur_remaining": True, "tab_enabled": True,
                "see_all": False, "selection_mode": "stable_random", "display_state": "active",
            }}},
            "daily": {"enabled": True, "plans": {"rookie": {
                "visible_rows": 1, "blur_remaining": True, "tab_enabled": True,
                "see_all": False, "selection_mode": "stable_random", "display_state": "active",
            }}},
            "value": {"enabled": True, "plans": {"rookie": {
                "visible_rows": 1, "blur_remaining": True, "tab_enabled": True,
                "see_all": False, "selection_mode": "stable_random", "display_state": "active",
            }}},
        }}}
    }
    payload = feed(10)

    # Search a deterministic account id whose daily hash does not select slot 1;
    # this makes the regression independent of the calendar date.
    found = None
    for i in range(200):
        access = {"status": "active", "plan": "rookie", "id": f"random-user-{i}"}
        data, manifest = filter_feed_for_access(payload, access, cfg)
        states = manifest["sections"]["prime"]["slot_states"]
        active = [idx for idx, state in enumerate(states[:10]) if state == "active"]
        if active and active[0] > 0:
            found = (data, manifest, active[0], access)
            break
    assert found is not None

    data, manifest, active_index, access = found
    assert manifest["sections"]["prime"]["returned"] == 1
    assert data["prime_picks"][0]["event_id"] == payload["prime_picks"][active_index]["event_id"]
    assert manifest["sections"]["prime"]["slot_states"][0] == "blurred"

    # Refreshing the same account on the same day must keep the same unlocked slot.
    data2, manifest2 = filter_feed_for_access(payload, access, cfg)
    assert data2["prime_picks"][0]["event_id"] == data["prime_picks"][0]["event_id"]
    assert manifest2["sections"]["prime"]["slot_states"] == manifest["sections"]["prime"]["slot_states"]


def _stable_random_cfg(plan: str, visible_rows: int) -> dict:
    return {
        "dashboard": {"daily_hub": {"enabled": True, "tabs": {
            "prime": {"enabled": True, "plans": {plan: {
                "visible_rows": visible_rows,
                "blur_remaining": True,
                "tab_enabled": True,
                "see_all": False,
                "selection_mode": "stable_random",
                "display_state": "active",
            }}},
        }}}
    }


def test_rookie_empty_daily_allocation_can_fill_later_without_rerolling():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    access = {"status": "active", "plan": "rookie", "id": "rookie-fill"}
    cfg = _stable_random_cfg("rookie", 1)

    empty_state, changed = build_daily_access_state(
        access,
        feed(0),
        cfg,
        now=now,
    )
    assert changed is True
    assert empty_state["sections"]["prime"] == []

    filled_state, changed2 = build_daily_access_state(
        access,
        feed(5),
        cfg,
        existing_day=empty_state["day"],
        existing_allocations=empty_state["sections"],
        now=now,
    )
    assert changed2 is True
    assert len(filled_state["sections"]["prime"]) == 1

    stable_state, changed3 = build_daily_access_state(
        access,
        feed(8),
        cfg,
        existing_day=filled_state["day"],
        existing_allocations=filled_state["sections"],
        now=now,
    )
    assert changed3 is False
    assert stable_state["sections"]["prime"] == filled_state["sections"]["prime"]


def test_pro_daily_allocation_only_fills_missing_slots_and_keeps_existing_pick():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    access = {"status": "active", "plan": "pro", "id": "pro-fill"}
    cfg = _stable_random_cfg("pro", 3)

    first_state, changed = build_daily_access_state(
        access,
        feed(1),
        cfg,
        now=now,
    )
    assert changed is True
    assert len(first_state["sections"]["prime"]) == 1
    original = list(first_state["sections"]["prime"])

    full_state, changed2 = build_daily_access_state(
        access,
        feed(6),
        cfg,
        existing_day=first_state["day"],
        existing_allocations=first_state["sections"],
        now=now,
    )
    assert changed2 is True
    assert len(full_state["sections"]["prime"]) == 3
    assert full_state["sections"]["prime"][:1] == original
