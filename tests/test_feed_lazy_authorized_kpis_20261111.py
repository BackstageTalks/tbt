"""Feed KPI computation: exactly one call, with authorized fallback parity.

Use a pure in-memory fake of the authenticated feed dependencies. No Azure
reads, writes, entitlement changes or CDB calls are involved in these tests.
"""
from types import SimpleNamespace

import pytest
import function_app as api


def _stub_authenticated_feed(monkeypatch, *, fail_at=None):
    calls = []
    authorized = {"event_id": "authorized"}
    settled = {"event_id": "settled"}
    raw = {"results": [{"event_id": "global"}], "top_daily_picks": []}

    monkeypatch.setattr(api, "_verified_user", lambda _req: {"id": "user-1", "email_verified": True})
    monkeypatch.setattr(api, "_profile_for", lambda _user: {})
    monkeypatch.setattr(api, "public_account", lambda _user, **_kw: {"plan": "rookie"})
    monkeypatch.setattr(api, "_read_feed_with_confirmed_aces_ou", lambda: raw)
    monkeypatch.setattr(api, "_visible_issued_feed", lambda feed: feed)
    monkeypatch.setattr(api, "with_issued_ace_leader_signals", lambda feed: feed)
    monkeypatch.setattr(api, "annotate_most_aces_offer", lambda feed: feed)
    monkeypatch.setattr(api, "_feed_support_reads_parallel", lambda: {
        "archive": ([], None),
        "statuses": ({}, None),
        "exclusions": (set(), None),
        "ui": (({}, None, None), None),
    })
    monkeypatch.setattr(api, "merge_settled_results", lambda feed, _archive: feed)
    monkeypatch.setattr(api, "apply_result_exclusions", lambda feed, _exclusions: feed)
    monkeypatch.setattr(api, "_access_context_with_daily_allocation",
                        lambda *_args, **_kw: {"plan": "rookie"})
    monkeypatch.setattr(api, "filter_feed_for_access",
                        lambda *_args: ({"results": [authorized]}, {"results": True, "result_categories": ["top_daily"]}))
    monkeypatch.setattr(api, "is_admin", lambda *_args: False)
    monkeypatch.setattr(api, "list_project_groups", lambda **_kw: {"items": []})
    monkeypatch.setattr(api, "event_ids_from_feed", lambda _feed: set())
    monkeypatch.setattr(api, "verified_terminal_statuses", lambda _statuses: {})
    monkeypatch.setattr(api, "runtime_settled_results",
                        lambda _feed, _statuses: [settled])
    monkeypatch.setattr(api, "filter_results_for_categories",
                        lambda results, _categories: results)
    monkeypatch.setattr(api, "filter_results_for_member_limits",
                        lambda results, *_args, **_kw: results)
    def filter_issued(results, *_args, **_kw):
        if fail_at == "before_final":
            raise api.AdminStorageUnavailable("simulated post-settlement read outage")
        return results
    monkeypatch.setattr(api, "filter_results_for_issued_day", filter_issued)
    def overlay(feed, _updates):
        if fail_at == "after_final":
            raise api.AdminStorageUnavailable("simulated schedule overlay outage")
        return feed
    monkeypatch.setattr(api, "apply_verified_schedule_overlay", overlay)
    def dashboard_cards(feed, _ui):
        event_ids = tuple(row["event_id"] for row in feed.get("results") or [])
        calls.append(event_ids)
        return [{"source_event_ids": event_ids}]
    monkeypatch.setattr(api, "selected_dashboard_cards", dashboard_cards)
    monkeypatch.setattr(api, "attach_offer_clv", lambda feed: feed)
    monkeypatch.setattr(api, "response", lambda data, status=200: data)
    return calls


def test_healthy_feed_computes_kpi_once_after_member_results_recheck(monkeypatch):
    calls = _stub_authenticated_feed(monkeypatch)
    served = api.feed(SimpleNamespace(params={}))
    assert calls == [("settled",)]
    assert served["dashboard_kpi_cards"] == [{"source_event_ids": ("settled",)}]
    assert served["results"] == [{"event_id": "settled"}]


def test_failed_results_overlay_uses_only_original_member_authorized_kpi(monkeypatch):
    calls = _stub_authenticated_feed(monkeypatch, fail_at="before_final")
    served = api.feed(SimpleNamespace(params={}))
    assert calls == [("authorized",)]
    assert served["dashboard_kpi_cards"] == [{"source_event_ids": ("authorized",)}]
    assert served["match_statuses"] == {}
    assert served["match_status_updated_at"] is None


def test_failure_after_final_kpi_does_not_overwrite_final_value(monkeypatch):
    calls = _stub_authenticated_feed(monkeypatch, fail_at="after_final")
    served = api.feed(SimpleNamespace(params={}))
    assert calls == [("settled",)]
    assert served["dashboard_kpi_cards"] == [{"source_event_ids": ("settled",)}]
    assert served["match_statuses"] == {}
