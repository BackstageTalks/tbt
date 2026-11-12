"""Concurrency and security tests for the production feed's read-only startup overlap."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from types import SimpleNamespace
from pathlib import Path

import pytest
import function_app as api

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
FEED = SOURCE[
    SOURCE.index('@app.route(route="v1/feed", methods=["GET"])'):
    SOURCE.index('@app.route(route="v1/internal/clv-snapshot"')
]


def test_independent_reads_start_together_and_keep_original_source(monkeypatch):
    barrier = Barrier(2, timeout=5)
    raw = {"daily_offer_day": "2026-11-12", "source": "canonical"}
    arrivals = []
    mutex = Lock()

    def issued(payload):
        with mutex:
            arrivals.append("issued")
        barrier.wait()
        return {"published": payload}

    def overlays():
        with mutex:
            arrivals.append("overlays")
        barrier.wait()
        return {"archive": ([], None)}

    monkeypatch.setattr(api, "_read_feed_with_confirmed_aces_ou", lambda: raw)
    monkeypatch.setattr(api, "_visible_issued_feed", issued)
    monkeypatch.setattr(api, "_feed_support_reads_parallel", overlays)
    with ThreadPoolExecutor(max_workers=2) as pool:
        issued_future, overlays_future = api._prefetch_independent_feed_reads(pool)
        assert issued_future.result() == {"published": raw}
        assert overlays_future.result() == {"archive": ([], None)}
    assert sorted(arrivals) == ["issued", "overlays"]


@pytest.mark.parametrize("failure_source", ["issued", "overlays"])
def test_independent_reads_propagate_source_errors_at_original_boundary(monkeypatch, failure_source):
    failure = api.AdminStorageUnavailable("simulated authority/storage failure")

    def issued(payload):
        if failure_source == "issued":
            raise failure
        return payload

    def overlays():
        if failure_source == "overlays":
            raise failure
        return {"ui": ({}, None)}

    monkeypatch.setattr(api, "_read_feed_with_confirmed_aces_ou", lambda: {})
    monkeypatch.setattr(api, "_visible_issued_feed", issued)
    monkeypatch.setattr(api, "_feed_support_reads_parallel", overlays)
    with ThreadPoolExecutor(max_workers=2) as pool:
        issued_future, overlays_future = api._prefetch_independent_feed_reads(pool)
        if failure_source == "issued":
            with pytest.raises(api.AdminStorageUnavailable) as observed:
                issued_future.result()
            assert observed.value is failure
            assert overlays_future.result() == {"ui": ({}, None)}
        else:
            assert issued_future.result() == {}
            with pytest.raises(api.AdminStorageUnavailable) as observed:
                overlays_future.result()
            assert observed.value is failure


def test_authentication_and_account_profile_proceed_before_feed_authority_is_consumed():
    assert FEED.index('return response({"error": "unauthorized"}, 401)') < FEED.index(
        'issued_future, overlays_future = _prefetch_independent_feed_reads(pool)'
    )
    assert FEED.index('return response({"error": "email_not_verified"}, 403)') < FEED.index(
        'issued_future, overlays_future = _prefetch_independent_feed_reads(pool)'
    )
    assert FEED.index('issued_future, overlays_future = _prefetch_independent_feed_reads(pool)') < FEED.index(
        'profile = _profile_for(user)'
    )
    assert FEED.index('profile = _profile_for(user)') < FEED.index(
        'source_feed = issued_future.result()'
    )
    assert FEED.index('source_feed = issued_future.result()') < FEED.index(
        'source_feed = with_issued_ace_leader_signals(source_feed)'
    )
    assert FEED.index('support_reads = overlays_future.result()') < FEED.index(
        'merge_settled_results(source_feed, _feed_support_value(support_reads, "archive"))'
    )
    for token in (
        'source_feed = apply_result_exclusions(source_feed, excluded_result_ids)',
        'filter_feed_for_access(source_feed, access_context, runtime_ui)',
        'filter_results_for_categories(', 'filter_results_for_member_limits(',
        'filter_results_for_issued_day(', 'selected_dashboard_cards(',
        'list_project_groups(user_id=str(user.get("id") or ""), include_inactive=False, joined_only=True)',
        'data = attach_offer_clv(data)',
    ):
        assert token in FEED, token


@pytest.mark.parametrize("verified", [False, True])
def test_unverified_or_anonymous_requests_do_not_start_storage_prefetch(monkeypatch, verified):
    calls = []
    monkeypatch.setattr(api, "_verified_user", lambda req: {"email_verified": False} if verified else None)
    monkeypatch.setattr(api, "_prefetch_independent_feed_reads", lambda pool: calls.append(True))
    monkeypatch.setattr(api, "response", lambda data, status=200: (data, status))
    outcome = api.feed(SimpleNamespace(params={}))
    assert outcome == (({"error": "email_not_verified"}, 403) if verified
                       else ({"error": "unauthorized"}, 401))
    assert not calls


def test_real_handler_overlaps_profile_and_both_independent_read_paths(monkeypatch):
    """Serial reads deadlock here; no Azure/network calls or behavior shortcuts."""
    from test_feed_lazy_authorized_kpis_20261111 import _stub_authenticated_feed
    # The existing stub preserves the full feed handler's settlement, KPIs,
    # account and authentication flow; replace only the three reader entrypoints.
    calls = _stub_authenticated_feed(monkeypatch)
    rendezvous = Barrier(3, timeout=8)
    events = []
    lock = Lock()
    def arrived(label):
        with lock:
            events.append(label)
        rendezvous.wait()
    def profile(_user):
        arrived("profile")
        return {}
    def issued():
        arrived("issued")
        return {"results": [], "top_daily_picks": []}
    def support():
        arrived("support")
        return {
            "archive": ([], None), "statuses": ({}, None),
            "exclusions": (set(), None), "ui": (({}, None, None), None),
        }
    monkeypatch.setattr(api, "_profile_for", profile)
    monkeypatch.setattr(api, "_read_feed_with_confirmed_aces_ou", issued)
    monkeypatch.setattr(api, "_feed_support_reads_parallel", support)
    feed = api.feed(SimpleNamespace(params={}))
    assert sorted(events) == ["issued", "profile", "support"]
    assert calls == [("settled",)]
    assert feed["dashboard_kpi_cards"] == [{"source_event_ids": ("settled",)}]
