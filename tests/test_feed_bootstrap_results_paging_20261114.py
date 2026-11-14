"""Contract for opt-in bootstrap and complete, member-authorized Results pages."""
from types import SimpleNamespace

import function_app as api
from test_feed_lazy_authorized_kpis_20261111 import _stub_authenticated_feed


def request(**params):
    return SimpleNamespace(params=params, headers={})


def test_bootstrap_skips_old_history_but_kpi_remains_complete(monkeypatch):
    computed = _stub_authenticated_feed(monkeypatch)
    normal = api.feed(request())
    assert normal["results"] == [{"event_id": "settled"}]
    assert "results_boot_partial" not in normal

    # The test fixture has no scheduled date, so it belongs to full history
    # but cannot be counted in the "recent" bootstrap preview.
    boot = api.feed(request(blinq_feed_view="bootstrap"))
    assert boot["results"] == []
    assert boot["results_boot_partial"] is True
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
