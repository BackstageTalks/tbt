from copy import deepcopy

import pytest

from tbt.services import manual_collection as collection


@pytest.fixture
def ledger(monkeypatch):
    rows = []

    def read():
        return (deepcopy(rows[-1]), len(rows)) if rows else (None, None)

    def store(item, etag):
        assert etag == read()[1]
        rows.append(deepcopy(item))

    monkeypatch.setattr(collection, "_read", read)
    monkeypatch.setattr(collection, "_store", store)
    monkeypatch.setattr(collection, "_remaining", lambda: 125)
    return rows


def test_manual_collection_claims_once_and_verifies_exact_run(ledger):
    payload = {"area": "break-points", "max_requests": 100}
    item = collection.start(payload, "admin-id")
    assert "actor" not in item
    with pytest.raises(collection.CollectionConflict):
        collection.start(payload, "other-admin")

    observation = {"id": item["id"], "run": None}
    pending = collection.sync(observation)["pending"]
    assert pending["state"] == "dispatching"
    assert collection.workflow_inputs(pending) == {
        "request_id": item["id"], "mode": "statistics", "break_points_focus": "true",
        "lookback_days": "365", "max_requests": "100", "promote": "false",
    }
    assert collection.sync(observation)["pending"] is None

    run = {"id": 42, "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
           "head_branch": "main", "display_title": "Some other run"}
    with pytest.raises(ValueError):
        collection.sync({**observation, "run": run})
    run["display_title"] = collection.RUN_TITLE + item["id"]
    collection.sync({**observation, "run": run})
    assert collection.status()["collection"]["state"] == "completed"
    assert collection.status()["collection"]["run_id"] == 42
    assert collection.status()["can_start"]


def test_manual_collection_rejects_invalid_or_unavailable_budget(ledger, monkeypatch):
    for payload in ({"area": "train", "max_requests": 10}, {"area": "extras", "max_requests": True},
                    {"area": "identity", "max_requests": 501}):
        with pytest.raises(ValueError):
            collection.start(payload, "admin")
    with pytest.raises(collection.CollectionConflict):
        collection.start({"area": "statistics", "max_requests": 126}, "admin")
    assert ledger == []
    item = collection.start({"area": "identity", "max_requests": 100}, "admin")
    monkeypatch.setattr(collection, "_remaining", lambda: 99)
    assert collection.sync({"id": item["id"], "run": None})["pending"] is None
    assert collection.status()["collection"]["state"] == "waiting_for_budget"
