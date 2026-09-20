from tbt.services.entitlements import filter_feed_for_access, effective_plan


def row(i):
    return {"event_id": str(i), "winner_id": "a", "signals": ["x"], "betting": {"odds": 2.0},
            "player1": {"id": "a", "name": "A", "probability": .7},
            "player2": {"id": "b", "name": "B", "probability": .3}}


def feed(n=8):
    keys = ["prime_picks", "top_daily_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks"]
    payload = {key: [row(i) for i in range(n)] for key in keys}
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
    assert len(data["top_daily_picks"]) == 2
    assert len(data["value_picks"]) == 0
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
    # The ordinary Results payload stays intact; Board owns only a derived view.
    assert data["results"] == payload["results"]


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
