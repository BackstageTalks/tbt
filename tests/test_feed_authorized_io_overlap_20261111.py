"""Feed I/O overlap: authorization order and original result/error policies stay intact."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import function_app as api


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
FEED = SOURCE[
    SOURCE.index('@app.route(route="v1/feed", methods=["GET"])'):
    SOURCE.index('@app.route(route="v1/internal/clv-snapshot"')
]


def test_issued_and_support_reads_start_concurrently(monkeypatch):
    # The two I/O paths must both start before either can return.
    barrier = Barrier(2, timeout=10)
    raw = {"daily_offer_day": "2026-11-11", "sentinel": object()}
    observed = []

    def issued(payload):
        observed.append(("issued", payload))
        barrier.wait()
        return {"issued": payload}

    def overlays():
        observed.append(("overlays", None))
        barrier.wait()
        return {"archive": ("sample", None)}

    monkeypatch.setattr(api, "_read_feed_with_confirmed_aces_ou", lambda: raw)
    monkeypatch.setattr(api, "_visible_issued_feed", issued)
    monkeypatch.setattr(api, "_feed_support_reads_parallel", overlays)
    with ThreadPoolExecutor(max_workers=2) as pool:
        issued_future, overlays_future = api._prefetch_independent_feed_reads(pool)
        assert issued_future.result() == {"issued": raw}
        assert overlays_future.result() == {"archive": ("sample", None)}
    assert {name for name, _ in observed} == {"issued", "overlays"}


@pytest.mark.parametrize("failed_reader", ["issued", "overlays"])
def test_prefetch_propagates_original_exceptions_at_result_boundary(monkeypatch, failed_reader):
    marker = RuntimeError("preserve original storage error policy")
    def issued(payload):
        if failed_reader == "issued":
            raise marker
        return {"issued": True}

    def overlays():
        if failed_reader == "overlays":
            raise marker
        return {"archive": (None, None)}

    monkeypatch.setattr(api, "_read_feed_with_confirmed_aces_ou", lambda: {})
    monkeypatch.setattr(api, "_visible_issued_feed", issued)
    monkeypatch.setattr(api, "_feed_support_reads_parallel", overlays)
    with ThreadPoolExecutor(max_workers=2) as pool:
        issued_future, overlays_future = api._prefetch_independent_feed_reads(pool)
        if failed_reader == "issued":
            with pytest.raises(RuntimeError) as error:
                issued_future.result()
            assert error.value is marker
            assert overlays_future.result() == {"archive": (None, None)}
        else:
            assert issued_future.result() == {"issued": True}
            with pytest.raises(RuntimeError) as error:
                overlays_future.result()
            assert error.value is marker


def test_authentication_precedes_prefetch_and_all_server_authorization_stays():
    # No expensive I/O prefetch before the authenticated user and email verification.
    assert FEED.index('return response({"error": "unauthorized"}, 401)') < FEED.index(
        "issued_future, overlays_future = _prefetch_independent_feed_reads(pool)"
    )
    assert FEED.index('return response({"error": "email_not_verified"}, 403)') < FEED.index(
        "issued_future, overlays_future = _prefetch_independent_feed_reads(pool)"
    )
    assert FEED.index("issued_future, overlays_future = _prefetch_independent_feed_reads(pool)") < FEED.index(
        "profile = _profile_for(user)"
    )
    assert FEED.index("profile = _profile_for(user)") < FEED.index(
        "account_data = public_account(user, cfg=settings, profile=profile)"
    )
    assert FEED.index("source_feed = issued_future.result()") < FEED.index(
        "source_feed = with_issued_ace_leader_signals(source_feed)"
    )
    assert FEED.index("support_reads = overlays_future.result()") < FEED.index(
        'merge_settled_results(source_feed, _feed_support_value(support_reads, "archive"))'
    )
    assert 'source_feed = apply_result_exclusions(source_feed, excluded_result_ids)' in FEED
    assert 'data, entitlements = filter_feed_for_access(source_feed, access_context, runtime_ui)' in FEED
    assert 'list_project_groups(user_id=str(user.get("id") or ""), include_inactive=False, joined_only=True)' in FEED
    assert 'data = attach_offer_clv(data)' in FEED
    # Keep the same traces for post-deployment performance comparisons.
    for stage in ("auth_verified", "account_profile", "account_public",
                  "issued_feed", "aces_projection", "support_reads",
                  "access_filter", "results_kpis", "clv_complete"):
        assert f'trace_stage("{stage}")' in FEED
