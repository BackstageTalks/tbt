"""Transient GitHub API retry contract for the Admin worker.

GET is safe to retry. Ambiguous POST dispatch MUST remain one-shot.
"""
import io
from urllib.error import HTTPError

import pytest
from tbt.services import model_training as mt


def test_admin_github_timeout_read_retries_bounded(monkeypatch):
    monkeypatch.setenv("BLINQ_TRAINING_GITHUB_TOKEN", "fixture-token")
    calls, sleeps = [], []

    def open_url(req, timeout):
        calls.append(timeout)
        if len(calls) < 3:
            raise TimeoutError("simulated read-only network timeout")
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(mt, "urlopen", open_url)
    monkeypatch.setattr(mt.time, "sleep", sleeps.append)
    assert mt.github("BackstageTalks/tbt/actions/runs/123") == {"ok": True}
    assert calls == [15, 15, 15] and sleeps == [1, 2]


def test_admin_github_post_is_never_replayed_after_timeout(monkeypatch):
    monkeypatch.setenv("BLINQ_TRAINING_DISPATCH_TOKEN", "fixture-token")
    calls, sleeps = [], []

    def open_url(req, timeout):
        calls.append(req.get_method())
        raise TimeoutError("dispatch outcome unknown")

    monkeypatch.setattr(mt, "urlopen", open_url)
    monkeypatch.setattr(mt.time, "sleep", sleeps.append)
    with pytest.raises(mt.TrainingUnavailable):
        mt.github("BackstageTalks/tbt/actions/workflows/x/dispatches", {"ref": "main"})
    assert calls == ["POST"] and sleeps == []


def test_admin_github_unauthorized_read_does_not_retry(monkeypatch):
    monkeypatch.setenv("BLINQ_TRAINING_GITHUB_TOKEN", "fixture-token")
    calls, sleeps = [], []

    def open_url(req, timeout):
        calls.append(req.get_method())
        raise HTTPError(req.full_url, 403, "forbidden", {}, None)

    monkeypatch.setattr(mt, "urlopen", open_url)
    monkeypatch.setattr(mt.time, "sleep", sleeps.append)
    with pytest.raises(mt.TrainingUnavailable):
        mt.github("BackstageTalks/tbt")
    assert calls == ["GET"] and sleeps == []


def test_admin_github_missing_ok_is_still_one_attempt(monkeypatch):
    monkeypatch.setenv("BLINQ_TRAINING_GITHUB_TOKEN", "fixture-token")
    calls = []

    def open_url(req, timeout):
        calls.append(req.get_method())
        raise HTTPError(req.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(mt, "urlopen", open_url)
    assert mt.github("BackstageTalks/tbt/git/ref/tags/not-there", missing_ok=True) is None
    assert calls == ["GET"]
