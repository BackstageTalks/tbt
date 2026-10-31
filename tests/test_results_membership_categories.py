"""Results must never expose a category disabled for the authenticated tier."""

import pytest

from tbt.services.entitlements import filter_feed_for_access


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
    tabs = {}
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
    ("elite", {"top_daily", "prime", "value", "doubles", "aces", "double_faults", "sets", "games"}),
    ("legend", {"top_daily", "prime", "value", "doubles", "aces", "double_faults", "sets", "games"}),
    ("goat", {"top_daily", "prime", "value", "doubles", "aces", "double_faults", "sets", "games"}),
    ("admin", {"top_daily", "prime", "value", "doubles", "aces", "double_faults", "sets", "games"}),
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
    assert set(_returned(data)) == {"top_daily", "aces", "sets"}
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
        assert len(_returned(data)) == 7
    admin, ent = _read("admin", cfg)
    assert len(_returned(admin)) == 8
    assert len(ent["result_categories"]) == 8


def test_all_categories_disabled_fails_closed_with_zero_rows():
    cfg = _config({
        ("elite", cat): {"visible_rows": 0, "display_state": "active"}
        for cat in ("top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games")
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
