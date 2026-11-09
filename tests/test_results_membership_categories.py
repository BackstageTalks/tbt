"""Results must never expose a category disabled for the authenticated tier."""

import pytest
from copy import deepcopy

from tbt.services.entitlements import filter_feed_for_access, filter_results_for_categories


def _published(section, market="match_winner"):
    return {
        "section": section,
        "market": market,
        "issued_at": "2026-10-30T09:00:00+00:00",
        "selection": "Player A",
        "result": {"correct": True, "status": "settled"},
    }


def _payload():
    return {
        "results": [{
            "event_id": "mix-1",
            "scheduled_at": "2026-10-30T12:00:00+00:00",
            "player1": {"name": "Player A"},
            "player2": {"name": "Player B"},
            "market_publications": [
                _published("top_daily"),
                _published("prime"),
                _published("value"),
                _published("doubles"),
                _published("ace", "aces"),
                _published("ace_winner", "most_aces"),
                # A historical inconsistent section must not promote DF into Aces.
                _published("ace", "double_faults"),
                _published("sets", "sets"),
                _published("games", "games"),
            ],
        }],
        "daily_picks": [],
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }


def _config(changes=None):
    # Model a published dashboard with independently configured SETS and
    # DOUBLE FAULTS. A missing rule intentionally inherits GAMES/ACES on old UI.
    tabs = {}
    for tab in ("sets", "double_faults"):
        tabs[tab] = {"plans": {
            plan: {"visible_rows": "ALL" if plan in ("elite", "legend", "goat") else 0,
                   "display_state": "active"}
            for plan in ("rookie", "pro", "elite", "legend", "goat")
        }}
    for (plan, category), settings in (changes or {}).items():
        tab = {"top_daily": "daily", "ace": "ace", "double_faults": "double_faults"}.get(category, category)
        tabs.setdefault(tab, {"plans": {}})["plans"][plan] = settings
    return {
        "elements": {"SIDEBAR_RESULTS": {
            "access": {p: "active" for p in ("rookie", "pro", "elite", "legend", "goat")},
        }},
        "dashboard": {
            "results_history_window": {p: "all" for p in ("rookie", "pro", "elite", "legend", "goat")},
            "daily_hub": {"tabs": tabs},
        },
    }


def _read(plan, cfg, payload=None):
    account = {"plan": plan, "status": "active"}
    if plan == "admin":
        account["role"] = "admin"
    return filter_feed_for_access(payload or _payload(), account, cfg)


def _returned(data):
    return [p["market"] if p["market"] != "match_winner" else p["section"]
            for row in data["results"] for p in row["market_publications"]]


@pytest.mark.parametrize("plan, expected", [
    ("rookie", {"top_daily", "prime", "value"}),
    ("pro", {"top_daily", "prime", "value"}),
    ("elite", {"top_daily", "prime", "value", "doubles", "aces", "most_aces", "double_faults", "sets", "games"}),
    ("legend", {"top_daily", "prime", "value", "doubles", "aces", "most_aces", "double_faults", "sets", "games"}),
    ("goat", {"top_daily", "prime", "value", "doubles", "aces", "most_aces", "double_faults", "sets", "games"}),
    ("admin", {"top_daily", "prime", "value", "doubles", "aces", "most_aces", "double_faults", "sets", "games"}),
])
def test_default_results_respect_each_tiers_market_permissions(plan, expected):
    data, ent = _read(plan, _config())
    assert set(_returned(data)) == expected
    assert len(data["results"]) == 1
    assert ("ace" in ent["result_categories"]) is (plan not in {"rookie", "pro"})


def test_elite_mixed_row_strips_disabled_blurred_hidden_and_zero_categories():
    cfg = _config(
        {
            ("elite", "prime"): {"visible_rows": 0, "display_state": "active"},
            ("elite", "value"): {"visible_rows": "ALL", "display_state": "blurred"},
            ("elite", "doubles"): {"visible_rows": "ALL", "display_state": "hidden"},
            ("elite", "double_faults"): {"visible_rows": 0, "display_state": "active"},
            ("elite", "games"): {"visible_rows": "ALL", "display_state": "active", "tab_enabled": False},
        }
    )
    original = _payload()
    data, ent = _read("elite", cfg, original)
    assert set(_returned(data)) == {"top_daily", "aces", "most_aces", "sets"}
    assert "double_faults" not in ent["result_categories"]
    assert original == _payload()  # Never mutate canonical ledger.


def test_projection_market_owns_category_even_when_legacy_section_mismatches():
    cfg = _config({
        ("elite", "ace"): {"visible_rows": 0, "display_state": "active"},
        ("elite", "double_faults"): {"visible_rows": "ALL", "display_state": "active"},
    })
    data, ent = _read("elite", cfg)
    assert "double_faults" in _returned(data)
    assert "aces" not in _returned(data)
    assert "ace" not in ent["result_categories"]


def test_admin_keeps_complete_audit_with_disabled_categories():
    cfg = _config({
        ("elite", "ace"): {"visible_rows": 0},
        ("legend", "prime"): {"visible_rows": 0},
        ("goat", "games"): {"visible_rows": 0},
    })
    for plan in ("elite", "legend", "goat"):
        data, _ = _read(plan, cfg)
        assert len(_returned(data)) == 8
    admin, ent = _read("admin", cfg)
    assert len(_returned(admin)) == 9
    assert len(ent["result_categories"]) == 9


def test_all_categories_disabled_fails_closed_with_zero_rows():
    cfg = _config({
        ("elite", cat): {"visible_rows": 0, "display_state": "active"}
        for cat in ("top_daily", "prime", "value", "doubles", "ace", "ace_winner", "double_faults", "sets", "games")
    })
    data, ent = _read("elite", cfg)
    assert ent["results"] is True
    assert ent["result_categories"] == []
    assert data["results"] == []


def test_explicit_active_override_can_allow_a_category_with_zero_base():
    cfg = _config({
        ("elite", "games"): {"visible_rows": 0, "display_state": "active", "row_overrides": {"1": "active"}},
    })
    data, ent = _read("elite", cfg)
    assert "games" in ent["result_categories"]
    assert "games" in _returned(data)


def test_results_route_lock_overrides_market_entitlements():
    cfg = _config()
    cfg["elements"]["SIDEBAR_RESULTS"]["access"]["elite"] = "locked"
    data, ent = _read("elite", cfg)
    assert ent["result_categories"] == []
    assert data["results"] == []


def test_second_pass_removes_unentitled_publication_from_runtime_mixed_market_row():
    # An authorized daily row may embed a projection-market publication. Runtime
    # settlement must not reintroduce it into the member's historical results.
    overlay = _payload()["results"]
    original = deepcopy(overlay)
    kept = filter_results_for_categories(overlay, {"top_daily", "ace"})
    assert set(_returned({"results": kept})) == {"top_daily", "aces"}
    assert overlay == original
    assert filter_results_for_categories(overlay, set()) == []


def test_feed_route_rechecks_after_status_overlay_before_response():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "api/function_app.py").read_text(encoding="utf-8")
    assert 'data["results"] = runtime_settled_results(data, data["match_statuses"])' in app
    assert 'data["results"] = filter_results_for_categories(' in app
    assert 'entitlements.get("result_categories") or []' in app


def test_browser_uses_authoritative_categories_and_new_cache_key():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    app = (root / "web/app.js").read_text(encoding="utf-8")
    index = (root / "web/index.html").read_text(encoding="utf-8")
    assert 'state.feed?.entitlements?.result_categories' in app
    assert 'function availableResultCategories()' in app
    assert 'function authorizedResultPublication(publication)' in app
    assert '.filter(authorizedResultPublication)' in app
    assert '&results-access-20261031=1' in index


def test_restricted_markets_do_not_leak_through_raw_performance_windows():
    payload = _payload()
    for key in ("performance", "betting_performance", "performance_windows",
                "performance_window_summary", "performance_subgroups"):
        payload[key] = {"secret_all_categories": "hidden-market-result"}
    cfg = _config({("elite", "prime"): {"visible_rows": 0, "display_state": "active"}})
    elite, ent = _read("elite", cfg, payload)
    assert "prime" not in ent["result_categories"]
    for key in ("performance", "betting_performance", "performance_windows",
                "performance_window_summary", "performance_subgroups"):
        assert elite[key] == {}
    legend, _ = _read("legend", cfg, payload)
    assert legend["performance"]["secret_all_categories"] == "hidden-market-result"
    admin, _ = _read("admin", cfg, payload)
    assert admin["performance"]["secret_all_categories"] == "hidden-market-result"
    assert payload["performance"]["secret_all_categories"] == "hidden-market-result"


def test_more_aces_result_requires_its_own_level_permission_not_ou_permission():
    payload = _payload()
    cfg = _config({
        ("elite", "ace_winner"): {"visible_rows": 0, "display_state": "active"},
    })
    data, manifest = _read("elite", cfg, payload)
    assert "aces" in _returned(data)
    assert "most_aces" not in _returned(data)
    assert "ace" in manifest["result_categories"]
    assert "ace_winner" not in manifest["result_categories"]
    assert payload == _payload()

    cfg = _config({
        ("elite", "ace"): {"visible_rows": 0, "display_state": "active"},
        ("elite", "ace_winner"): {"visible_rows": "ALL", "display_state": "active"},
    })
    data, manifest = _read("elite", cfg)
    assert "aces" not in _returned(data)
    assert "most_aces" in _returned(data)
    assert "ace" not in manifest["result_categories"]
    assert "ace_winner" in manifest["result_categories"]


def _positioned_results(n=4, *, section="top_daily", market="match_winner"):
    """Distinct published bets; explicit slots survive missing/pending results."""
    rows = []
    for position in range(1, n + 1):
        rows.append({
            "event_id": f"{section}-{position}",
            "scheduled_at": "2026-10-30T12:00:00+00:00",
            "player1": {"id": "p1"}, "player2": {"id": "p2"},
            "market_publications": [{
                "section": section, "market": market,
                "selection_id": "p1", "selection": "A",
                "issued_at": "2026-10-30T08:00:00+00:00",
                "betting_day": "2026-10-30", "offer_position": position,
                "publication_status": "published",
                "price_status": "priced_projection" if market != "match_winner" else "priced",
                "odds": 1.66, "result": {"status": "hit", "correct": True},
            }],
        })
    return rows


@pytest.mark.parametrize("plan", ["rookie", "pro", "elite", "legend", "goat"])
def test_all_memberships_results_follow_admin_position_limits(plan):
    payload = _payload()
    payload["results"] = _positioned_results(5)
    payload["top_daily_picks"] = []
    config = _config({
        (plan, "top_daily"): {"visible_rows": 2, "display_state": "active"},
    })
    original = deepcopy(payload)
    data, ent = _read(plan, config, payload)
    assert [r["event_id"] for r in data["results"]] == ["top_daily-1", "top_daily-2"]
    assert ent["sections"]["daily"]["visible_picks"] == 2
    assert payload == original

    config["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"][plan]["visible_rows"] = 4
    expanded, _ = _read(plan, config, payload)
    assert [r["event_id"] for r in expanded["results"]] == [
        "top_daily-1", "top_daily-2", "top_daily-3", "top_daily-4"
    ]


@pytest.mark.parametrize("plan", ["rookie", "pro", "elite", "legend", "goat"])
def test_all_tiers_apply_hidden_row_overrides_and_disabled_categories(plan):
    payload = _payload()
    payload["results"] = _positioned_results(4) + _positioned_results(
        2, section="ace_winner", market="most_aces"
    )
    cfg = _config({
        (plan, "top_daily"): {
            "visible_rows": 2, "display_state": "active",
            "row_overrides": {"1": "hidden", "4": "active"},
        },
        (plan, "ace_winner"): {
            "visible_rows": "ALL", "display_state": "hidden",
        },
    })
    data, _ = _read(plan, cfg, payload)
    assert [r["event_id"] for r in data["results"]] == [
        "top_daily-2", "top_daily-4"
    ]
    cfg["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"][plan]["display_state"] = "blurred"
    denied, _ = _read(plan, cfg, payload)
    assert denied["results"] == []


def test_explicit_offer_position_preserves_pending_slot_and_prevents_result_backfill():
    payload = _payload()
    payload["results"] = _positioned_results(3)[1:]  # The first offer is unsettled.
    config = _config({
        ("pro", "top_daily"): {"visible_rows": 1, "display_state": "active"},
    })
    data, _ = _read("pro", config, payload)
    assert data["results"] == []  # Settled position #2 must not become position #1.
    config["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"]["pro"]["visible_rows"] = 2
    allowed, _ = _read("pro", config, payload)
    assert [r["event_id"] for r in allowed["results"]] == ["top_daily-2"]


def test_display_only_more_aces_bridge_does_not_enter_member_results_even_if_tab_allowed():
    payload = _payload()
    payload["results"] = _positioned_results(
        2, section="ace_winner", market="most_aces"
    )
    bridge = payload["results"][0]["market_publications"][0]
    bridge["ace_winner_issued"] = False
    bridge["price_status"] = "projection_only"
    cfg = _config({
        ("elite", "ace_winner"): {"visible_rows": "ALL", "display_state": "active"},
    })
    data, _ = _read("elite", cfg, payload)
    assert [r["event_id"] for r in data["results"]] == ["ace_winner-2"]


def test_stable_random_membership_result_positions_are_account_scoped_and_repeatable():
    payload = _payload()
    payload["results"] = _positioned_results(10, section="prime")
    cfg = _config({
        ("rookie", "prime"): {
            "visible_rows": 2, "display_state": "active",
            "selection_mode": "stable_random",
        },
    })
    account = {"status": "active", "plan": "rookie", "id": "member-alpha"}
    first, manifest = filter_feed_for_access(payload, account, cfg)
    second, _ = filter_feed_for_access(payload, account, cfg)
    assert [r["event_id"] for r in first["results"]] == [
        r["event_id"] for r in second["results"]
    ]
    assert len(first["results"]) == 2
    assert manifest["sections"]["prime"]["selection_mode"] == "stable_random"


def test_admin_keeps_full_audit_when_membership_limit_is_tightened():
    payload = _payload()
    payload["results"] = _positioned_results(5)
    cfg = _config({
        ("rookie", "top_daily"): {"visible_rows": 1, "display_state": "active"},
        ("elite", "top_daily"): {"visible_rows": 1, "display_state": "active"},
    })
    admin, _ = _read("admin", cfg, payload)
    assert len(admin["results"]) == 5


def test_runtime_post_settlement_rechecks_position_caps_not_only_category():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "api/function_app.py").read_text(
        encoding="utf-8"
    )
    assert app.count('data["results"] = filter_results_for_member_limits(') == 1
    assert "authorized_feed=data" in app


def test_current_day_uses_each_accounts_durable_random_allocation_not_recomputed_sample():
    from tbt.services.entitlements import blinq_access_day, _row_access_key
    day = blinq_access_day()
    payload = _payload()
    source = _positioned_results(5)
    payload["results"] = source
    payload["top_daily_picks"] = [
        {
            "event_id": row["event_id"], "winner_id": "p1",
            "selection_id": "p1", "odds": 2.0,
            "scheduled_at": day + "T12:00:00+00:00",
            "player1": {"id": "p1", "name": "A"},
            "player2": {"id": "p2", "name": "B"},
        }
        for row in source
    ]
    for row in source:
        row["scheduled_at"] = day + "T12:00:00+00:00"
        row["market_publications"][0]["issued_at"] = day + "T08:00:00+00:00"
        row["market_publications"][0]["betting_day"] = day
    cfg = _config({
        ("rookie", "top_daily"): {
            "visible_rows": 1, "display_state": "active",
            "selection_mode": "stable_random",
        },
    })
    for slot in (2, 4):
        account = {
            "id": "member-" + str(slot), "plan": "rookie", "status": "active",
            "_daily_allocations": {
                "daily": [_row_access_key(payload["top_daily_picks"][slot - 1])]
            },
        }
        data, ent = filter_feed_for_access(payload, account, cfg)
        assert [r["event_id"] for r in data["daily_picks"]] == [f"top_daily-{slot}"]
        assert [r["event_id"] for r in data["results"]] == [f"top_daily-{slot}"]
        assert ent["sections"]["daily"]["visible_picks"] == 1
        assert ent["member_daily_pick_count"] == 1


@pytest.mark.parametrize("plan", ["rookie", "pro", "elite", "legend", "goat"])
def test_member_offer_denominator_counts_only_unlocked_distinct_tips(plan):
    payload = _payload()
    payload["results"] = []
    payload["top_daily_picks"] = [{
        "event_id": f"bet-{i}", "winner_id": "p1", "selection_id": "p1",
        "odds": 2.0, "surface": "hard",
        "scheduled_at": "2026-11-09T12:00:00+00:00",
        "player1": {"id": "p1", "name": "A"},
        "player2": {"id": "p2", "name": "B"},
    } for i in range(1, 4)]
    config = _config({(plan, "top_daily"): {
        "visible_rows": 2, "display_state": "active",
    }})
    data, ent = _read(plan, config, payload)
    assert len(data["daily_picks"]) == 2
    assert ent["member_daily_pick_count"] == 2
    assert ent["daily_pick_count"] == 3  # Global telemetry stays unchanged.
    config["dashboard"]["daily_hub"]["tabs"]["daily"]["plans"][plan]["visible_rows"] = 1
    limited, next_ent = _read(plan, config, payload)
    assert len(limited["daily_picks"]) == 1
    assert next_ent["member_daily_pick_count"] == 1


def test_elite_excludes_large_more_aces_offer_but_legend_and_goat_retain_all():
    """The 62-match public universe is not the ELITE membership Results sample."""
    payload = _payload()
    # Nine TOP contracts and 53 independently issued VIAC ES contracts.
    payload["results"] = (
        _positioned_results(9, section="top_daily")
        + _positioned_results(53, section="ace_winner", market="most_aces")
    )
    config = _config({
        ("elite", "top_daily"): {"visible_rows": 5, "display_state": "active"},
        ("elite", "ace_winner"): {
            "visible_rows": "ALL", "display_state": "hidden",
        },
        ("legend", "top_daily"): {"visible_rows": "ALL", "display_state": "active"},
        ("legend", "ace_winner"): {"visible_rows": "ALL", "display_state": "active"},
        ("goat", "top_daily"): {"visible_rows": "ALL", "display_state": "active"},
        ("goat", "ace_winner"): {"visible_rows": "ALL", "display_state": "active"},
    })
    original = deepcopy(payload)
    elite, elite_ent = _read("elite", config, payload)
    assert [r["event_id"] for r in elite["results"]] == [
        f"top_daily-{i}" for i in range(1, 6)
    ]
    assert "ace_winner" not in elite_ent["result_categories"]

    for plan in ("legend", "goat"):
        visible, entitlement = _read(plan, config, payload)
        assert len(visible["results"]) == 62
        assert sum(
            pub["market"] == "most_aces"
            for row in visible["results"]
            for pub in row["market_publications"]
        ) == 53
        assert "ace_winner" in entitlement["result_categories"]
        assert entitlement["sections"]["ace_winner"]["visible_picks"] == "ALL"
    assert payload == original
