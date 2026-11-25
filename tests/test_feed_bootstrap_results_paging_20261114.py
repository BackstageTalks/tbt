"""Contract for opt-in bootstrap and complete, member-authorized Results pages."""
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import function_app as api
from test_feed_lazy_authorized_kpis_20261111 import _stub_authenticated_feed


def request(**params):
    return SimpleNamespace(params=params, headers={})


def test_bootstrap_defers_history_but_kpi_remains_complete(monkeypatch):
    computed = _stub_authenticated_feed(monkeypatch)
    normal = api.feed(request())
    assert normal["results"] == [{"event_id": "settled"}]
    assert "results_boot_partial" not in normal

    # Dashboard bootstrap no longer transfers *any* Results records; the
    # Results route hydrates the full authorized history when actually opened.
    boot = api.feed(request(blinq_feed_view="bootstrap"))
    assert boot["results"] == []
    assert boot["results_boot_partial"] is True
    assert boot["results_snapshot"] == api._authorized_results_revision(normal["results"])
    assert boot["dashboard_kpi_cards"] == normal["dashboard_kpi_cards"]
    assert computed == [("settled",), ("settled",)]


def test_results_pages_reconstruct_complete_authorized_ledger(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    first = api.results_page(request(page="0", limit="1"))
    assert first["results"] == [{"event_id": "settled"}]
    assert first["total"] == 1
    assert first["snapshot"]
    assert first["has_more"] is False
    second = api.results_page(request(page="1", limit="1", snapshot=first["snapshot"]))
    assert second["results"] == []
    assert second["total"] == first["total"]
    assert second["snapshot"] == first["snapshot"]
    assert "global" not in str(first), "Unfiltered source Results must not leak"
    assert api.results_page(request(page="0", limit="1", snapshot="stale")) == {
        "error": "results_snapshot_changed"
    }


def test_results_invalid_parameters_are_rejected_before_reading_feed(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    for params in (
        {"page": "-1"}, {"page": "not-int"}, {"limit": "0"},
        {"limit": "501"}, {"page": "100001"},
    ):
        assert api.results_page(request(**params)) == {"error": "invalid_results_page"}


def test_results_route_does_not_bypass_feed_verification(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    monkeypatch.setattr(api, "_verified_user", lambda req: None)
    assert api.results_page(request()) == {"error": "unauthorized"}
    monkeypatch.setattr(api, "_verified_user",
                        lambda req: {"id": "user-1", "email_verified": False})
    assert api.results_page(request()) == {"error": "email_not_verified"}



def test_bootstrap_defers_even_recent_results_with_same_kpi_and_full_paging(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    recent = {
        "event_id": "recent-settled",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
        "market_publications": [{"section": "top_daily", "result": {"correct": True}}],
    }
    monkeypatch.setattr(api, "runtime_settled_results",
                        lambda _feed, _statuses, **_kwargs: [recent])
    normal = api.feed(request())
    bootstrap = api.feed(request(blinq_feed_view="bootstrap"))
    page = api.results_page(request(page="0", limit="500"))

    assert normal["results"] == [recent]
    assert bootstrap["results"] == []
    assert bootstrap["results_boot_partial"] is True
    assert bootstrap["dashboard_kpi_cards"] == normal["dashboard_kpi_cards"]
    assert page["results"] == [recent]
    assert page["total"] == 1
    assert page["has_more"] is False


def test_empty_authorized_results_do_not_trigger_unnecessary_lazy_load(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    monkeypatch.setattr(api, "runtime_settled_results",
                        lambda _feed, _statuses, **_kwargs: [])
    boot = api.feed(request(blinq_feed_view="bootstrap"))
    assert boot["results"] == []
    assert boot["results_boot_partial"] is False


def test_bootstrap_revision_matches_pages_and_changes_with_authorized_results(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    first = api.feed(request(blinq_feed_view="bootstrap"))
    page = api.results_page(request(page="0", limit="500"))
    assert first["results_snapshot"] == page["snapshot"]
    assert first["results"] == []
    assert first["results_boot_partial"] is True
    assert len(first["results_snapshot"]) == 24
    assert api._authorized_results_revision([{"event_id": "other"}]) != first["results_snapshot"]


def test_empty_authorized_bootstrap_has_empty_revision(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    monkeypatch.setattr(api, "runtime_settled_results",
                        lambda _feed, _statuses, **_kwargs: [])
    feed = api.feed(request(blinq_feed_view="bootstrap"))
    assert feed["results_boot_partial"] is False
    assert feed["results_snapshot"] == api._authorized_results_revision([])


def test_recent_results_scope_only_transfers_30_betting_days(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    fresh = {"event_id": "recent", "scheduled_at": (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()}
    old = {"event_id": "old", "scheduled_at": (datetime.now(timezone.utc)-timedelta(days=50)).isoformat()}
    monkeypatch.setattr(api, "runtime_settled_results", lambda *_args, **_kwargs: [fresh, old])
    full = api.results_page(request(page="0", limit="500"))
    recent = api.results_page(request(page="0", limit="500", window_days="30"))
    bootstrap = api.feed(request(blinq_feed_view="bootstrap"))
    assert full["results"] == [fresh, old]
    assert recent["results"] == [fresh]
    assert recent["scope_days"] == 30
    assert recent["total"] == 1
    assert recent["snapshot"] == full["snapshot"] == bootstrap["results_snapshot"]
    assert api.results_page(request(page="0", limit="500", window_days="30", snapshot="stale")) == {
        "error": "results_snapshot_changed"
    }


def test_recent_results_scope_does_not_bypass_member_auth(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    monkeypatch.setattr(api, "_verified_user", lambda req: None)
    assert api.results_page(request(window_days="30")) == {"error": "unauthorized"}
    monkeypatch.setattr(api, "_verified_user",
                        lambda req: {"id": "user-1", "email_verified": False})
    assert api.results_page(request(window_days="30")) == {"error": "email_not_verified"}
    assert api.results_page(request(window_days="1")) == {"error": "email_not_verified"}
    assert api.results_page(request(window_days="31")) == {"error": "invalid_results_page"}



def test_today_scope_is_exact_bratislava_betting_day_and_snapshot_safe(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    zone = ZoneInfo("Europe/Bratislava")
    betting_day = (datetime.now(zone) - timedelta(hours=6)).date()
    start = datetime.combine(betting_day, time(hour=6), tzinfo=zone)
    next_start = datetime.combine(betting_day + timedelta(days=1), time(hour=6), tzinfo=zone)
    rows = [
        {"event_id": "before", "scheduled_at": (start-timedelta(seconds=1)).isoformat()},
        {"event_id": "start", "scheduled_at": start.isoformat()},
        {"event_id": "today", "scheduled_at": (start+timedelta(hours=6)).isoformat()},
        {"event_id": "end", "scheduled_at": next_start.isoformat()},
    ]
    monkeypatch.setattr(api, "runtime_settled_results", lambda *_args, **_kwargs: rows)
    full = api.results_page(request(page="0", limit="500"))
    today = api.results_page(request(page="0", limit="500", window_days="1"))
    assert [r["event_id"] for r in today["results"]] == ["start", "today"]
    assert today["scope_days"] == 1
    assert today["total"] == 2
    assert today["snapshot"] == full["snapshot"]
    assert api.results_page(request(window_days="1", snapshot="stale")) == {
        "error": "results_snapshot_changed"
    }
    assert api.results_page(request(window_days="2")) == {
        "error": "invalid_results_page"
    }



def test_results_only_matches_full_authorized_ledger_without_auxiliary_reads(monkeypatch):
    """Per-page Results must never recompute dashboard KPI or query UI-only storage."""
    computed = _stub_authenticated_feed(monkeypatch)
    complete = api.feed(request())
    assert computed == [("settled",)]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unrelated dashboard work ran on results-only request")

    for name in (
        "selected_dashboard_cards", "list_project_groups",
        "apply_verified_schedule_overlay", "attach_offer_clv",
        "entitlement_manifest",
    ):
        monkeypatch.setattr(api, name, forbidden)

    recent = api.results_page(request(window_days="30", page="0", limit="500"))
    all_time = api.results_page(request(page="0", limit="500"))
    assert recent["results"] == []  # Fake settled row has no timestamp.
    assert all_time["results"] == complete["results"]
    assert computed == [("settled",)]  # Only the normal /v1/feed computed KPI.
    assert recent["snapshot"] == all_time["snapshot"]
    assert not recent["has_more"]
    assert "global" not in str(all_time)


def test_results_only_admin_does_not_repeat_global_runtime_settlement(monkeypatch):
    _stub_authenticated_feed(monkeypatch)
    monkeypatch.setattr(api, "is_admin", lambda *_args: True)
    count = []
    def settle(_feed, _statuses, **_kwargs):
        count.append(_kwargs)
        return [{"event_id": "settled"}]
    monkeypatch.setattr(api, "runtime_settled_results", settle)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Admin-only KPI or tier presentation was evaluated")
    monkeypatch.setattr(api, "entitlement_manifest", forbidden)
    monkeypatch.setattr(api, "selected_dashboard_cards", forbidden)
    page = api.results_page(request(page="0", limit="500"))
    assert page["results"] == [{"event_id": "settled"}]
    assert len(count) == 1 and count[0].get("already_detached") is True


def test_results_only_preserves_existing_settlement_fallback_without_kpi(monkeypatch):
    calls = _stub_authenticated_feed(monkeypatch, fail_at="before_final")
    page = api.results_page(request(page="0", limit="500"))
    assert calls == []
    # Existing feed fallback retains the already-settled authorized row; the
    # result-only path must not accidentally apply new exclusion semantics.
    assert page["results"] == [{"event_id": "settled"}]
    assert page["snapshot"] == api._authorized_results_revision(page["results"])


def test_bootstrap_drops_board_results_history():
    src = (api.__file__ and open(api.__file__, encoding="utf-8").read())
    assert 'data["board_results"] = []' in src
    assert 'data["board_results_boot_partial"] = True' in src
