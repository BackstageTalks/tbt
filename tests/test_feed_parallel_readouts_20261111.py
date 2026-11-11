"""Authenticated feed startup: independent Azure reads overlap without changing policy."""
from threading import Barrier

import pytest
import function_app as api


def test_independent_feed_reads_start_concurrently(monkeypatch):
    # A serial implementation cannot pass: every reader waits for all four
    # others before returning. The test uses no storage or network.
    barrier = Barrier(4, timeout=10)
    read_names = ("archive", "statuses", "exclusions", "ui")
    targets = {
        "archive": "load_settled_results_archive",
        "statuses": "load_match_status_snapshot",
        "exclusions": "load_result_exclusions",
        "ui": "load_effective_ui_config",
    }

    def reader(name):
        barrier.wait()
        return {"source": name}

    for name in read_names:
        monkeypatch.setattr(api, targets[name], lambda name=name: reader(name))

    snapshot = api._feed_support_reads_parallel()
    assert set(snapshot) == set(read_names)
    for name in read_names:
        assert api._feed_support_value(snapshot, name) == {"source": name}


def test_read_errors_reach_existing_feed_policy_boundaries(monkeypatch):
    marker = RuntimeError("storage failed")
    calls = []

    def ok(name):
        calls.append(name)
        return {"source": name}

    monkeypatch.setattr(api, "load_settled_results_archive", lambda: ok("archive"))
    monkeypatch.setattr(api, "load_match_status_snapshot", lambda: ok("statuses"))
    monkeypatch.setattr(api, "load_result_exclusions", lambda: (_ for _ in ()).throw(marker))
    monkeypatch.setattr(api, "load_effective_ui_config", lambda: ok("ui"))

    snapshot = api._feed_support_reads_parallel()
    assert set(calls) == {"archive", "statuses", "ui"}
    with pytest.raises(RuntimeError) as observed:
        api._feed_support_value(snapshot, "exclusions")
    assert observed.value is marker
    assert api._feed_support_value(snapshot, "archive") == {"source": "archive"}
    assert api._feed_support_value(snapshot, "statuses") == {"source": "statuses"}
    assert api._feed_support_value(snapshot, "ui") == {"source": "ui"}
