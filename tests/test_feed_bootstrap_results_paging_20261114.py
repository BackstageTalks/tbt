"""Contract for opt-in bootstrap and complete, member-authorized Results pages."""
from datetime import datetime, timezone
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
