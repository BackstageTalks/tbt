import subprocess

import release_store


def test_gh_retries_transient_http_500(monkeypatch):
    calls = []
    sleeps = []
    results = [
        subprocess.CompletedProcess(["gh"], 1, "", "HTTP 500 (https://api.github.com/x)"),
        subprocess.CompletedProcess(["gh"], 0, "ok\n", ""),
    ]

    def run(command, capture_output, text):
        calls.append(command)
        return results.pop(0)

    monkeypatch.setattr(release_store.subprocess, "run", run)
    monkeypatch.setattr(release_store.time, "sleep", sleeps.append)

    assert release_store.gh("release", "view", "x") == "ok\n"
    assert len(calls) == 2
    assert sleeps == [2]


def test_gh_does_not_retry_nontransient_failure(monkeypatch):
    calls = []

    def run(command, capture_output, text):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "HTTP 404: Not Found")

    monkeypatch.setattr(release_store.subprocess, "run", run)
    monkeypatch.setattr(release_store.time, "sleep", lambda _delay: (_ for _ in ()).throw(AssertionError("sleep")))

    try:
        release_store.gh("api", "repos/x/y")
    except RuntimeError as exc:
        assert "HTTP 404" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    assert len(calls) == 1
