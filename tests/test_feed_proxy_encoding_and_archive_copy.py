"""Proxy transport negotiation and source isolation on the serving fast path."""
from copy import deepcopy
import gzip
import json
from types import SimpleNamespace

import pytest
import function_app as api
from tbt.services.entitlements import filter_feed_for_access
from tbt.services.results_archive import merge_settled_results
from test_feed_access_root_copy_20261112 import _source_feed, _ui
from test_feed_lazy_authorized_kpis_20261111 import _stub_authenticated_feed


@pytest.mark.parametrize("encoding", ["", "br", "identity"])
def test_explicit_browser_capability_survives_proxy_encoding_rewrite(monkeypatch, encoding):
    _stub_authenticated_feed(monkeypatch)
    req = SimpleNamespace(params={"blinq_feed_gzip": "1"}, headers={
        "Accept-Encoding": encoding, "X-Blinq-Feed-Encoding": "gzip",
    })
    reply = api.feed(req)
    assert reply.headers["Content-Encoding"] == "gzip"
    assert "blinq_json;dur=" in reply.headers["Server-Timing"]
    assert json.loads(gzip.decompress(reply.get_body()))["results"] == [{"event_id": "settled"}]


def test_custom_capability_cannot_override_explicit_refusal_or_auth(monkeypatch):
    req = SimpleNamespace(params={"blinq_feed_gzip": "1"}, headers={
        "Accept-Encoding": "gzip;q=0", "X-Blinq-Feed-Encoding": "gzip",
    })
    assert not api._feed_gzip_acceptable(req)
    _stub_authenticated_feed(monkeypatch)
    monkeypatch.setattr(api, "_verified_user", lambda req: None)
    assert api.feed(req) == {"error": "unauthorized"}


@pytest.mark.parametrize("plan", ["rookie", "pro", "elite", "legend", "goat", "admin"])
def test_borrowed_archive_metadata_is_detached_at_entitlement_boundary(plan):
    source = _source_feed()
    archive = deepcopy(source["results"])
    archive[0]["event_id"] = "archive-only"
    original, archive_original = deepcopy(source), deepcopy(archive)
    normal = merge_settled_results(source, archive)
    fast = merge_settled_results(source, archive, borrow_metadata=True)
    assert normal == fast
    assert fast["results"][0]["player1"] is not normal["results"][0]["player1"]
    account = {"plan": plan, "status": "active", "id": "member-1"}
    if plan == "admin":
        account["role"] = "admin"
    expected, expected_manifest = filter_feed_for_access(normal, account, _ui())
    actual, manifest = filter_feed_for_access(fast, account, _ui())
    assert actual == expected
    assert manifest == expected_manifest
    for row in actual["results"]:
        row["player1"]["name"] = "response mutation"
        row["market_publications"][0]["result"]["correct"] = False
    assert source == original
    assert archive == archive_original
    assert fast == normal, "response mutations must not change the KPI source"


def test_archive_fast_path_never_deepcopies_large_readonly_metadata(monkeypatch):
    import tbt.services.results_archive as archive_module
    source = _source_feed()
    source["results"][0]["player1"]["model"] = {"samples": list(range(10000))}
    original_copy = archive_module.deepcopy
    forbidden = source["results"][0]["player1"]
    def copy(value, *args, **kwargs):
        assert value is not source["results"][0]
        assert not (isinstance(value, dict) and value.get("player1") is forbidden)
        return original_copy(value, *args, **kwargs)
    monkeypatch.setattr(archive_module, "deepcopy", copy)
    fast = merge_settled_results(source, [], borrow_metadata=True)
    assert fast["results"][0]["player1"] is forbidden
    assert fast["results"][0]["market_publications"] is not source["results"][0]["market_publications"]
