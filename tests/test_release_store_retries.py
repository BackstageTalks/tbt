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


def _store_for_test(tmp_path):
    store = object.__new__(release_store.ReleaseStore)
    store.repository = "BackstageTalks/tbt-data"
    store.tag = "tbt-predictions-v1"
    store.directory = tmp_path
    return store


def test_stale_tag_manifest_404_recovers_from_fresh_release_asset_id(
    monkeypatch, tmp_path,
):
    import hashlib
    import json

    store = _store_for_test(tmp_path)
    feed = b'{"ready":true}'
    ledger = b'{"issued":[]}'
    manifest = json.dumps({
        "schema": 1,
        "files": {
            "feed.json": {"sha256": hashlib.sha256(feed).hexdigest(), "bytes": len(feed)},
            "ledger.json": {"sha256": hashlib.sha256(ledger).hexdigest(), "bytes": len(ledger)},
        },
    }).encode()
    store._asset_names = lambda: {
        store.BUNDLE_MANIFEST, "feed.json", "ledger.json",
    }
    calls = []

    def fake_gh(*args):
        calls.append(args)
        if args[:2] == ("release", "download"):
            name = args[args.index("--pattern") + 1]
            if name == store.BUNDLE_MANIFEST:
                raise RuntimeError(
                    "GitHub CLI operation failed: HTTP 404: Not Found "
                    "(https://api.github.com/repos/BackstageTalks/tbt-data/"
                    "releases/assets/583182647)"
                )
            (tmp_path / name).write_bytes({"feed.json": feed, "ledger.json": ledger}[name])
            return ""
        if args[0] == "api" and "--jq" in args:
            return "383532078\n"
        if args[0] == "api" and "--paginate" in args:
            return json.dumps([[{
                "id": 583341449, "name": store.BUNDLE_MANIFEST,
                "state": "uploaded", "size": len(manifest),
            }]])
        raise AssertionError(args)

    binary_calls = []

    def fake_run(cmd, *, stdout, stderr):
        binary_calls.append(cmd)
        stdout.write(manifest)
        return subprocess.CompletedProcess(cmd, 0, None, b"")

    monkeypatch.setattr(release_store, "gh", fake_gh)
    monkeypatch.setattr(release_store.subprocess, "run", fake_run)
    selected = store.download(required_names=("feed.json", "ledger.json"))
    assert selected == ["feed.json", "ledger.json"]
    assert (tmp_path / store.BUNDLE_MANIFEST).read_bytes() == manifest
    assert any("/383532078/assets?per_page=100" in " ".join(map(str, c)) for c in calls)
    assert len(binary_calls) == 1
    assert "583341449" in binary_calls[0][-1]
    assert not list(tmp_path.glob("*.part"))


def test_stale_release_fallback_rejects_incomplete_binary(monkeypatch, tmp_path):
    import json

    store = _store_for_test(tmp_path)
    target = tmp_path / "ledger.json"
    target.write_bytes(b"previous verified file")

    def fake_gh(*args):
        if args[:2] == ("release", "download"):
            raise RuntimeError("HTTP 404: stale tag asset")
        if "--jq" in args:
            return "383532078"
        return json.dumps([[{
            "id": 583341386, "name": "ledger.json",
            "state": "uploaded", "size": 1024,
        }]])

    def fake_run(cmd, *, stdout, stderr):
        stdout.write(b'{"id": 583341386}')  # API metadata, not asset bytes
        return subprocess.CompletedProcess(cmd, 0, None, b"")

    monkeypatch.setattr(release_store, "gh", fake_gh)
    monkeypatch.setattr(release_store.subprocess, "run", fake_run)
    import pytest
    with pytest.raises(RuntimeError, match="refusing a partial or non-binary"):
        store._download_asset("ledger.json")
    assert target.read_bytes() == b"previous verified file"
    assert not list(tmp_path.glob("*.part"))


def test_stale_release_fallback_never_hides_disappearing_required_asset(
    monkeypatch, tmp_path,
):
    import json
    import pytest

    store = _store_for_test(tmp_path)

    def fake_gh(*args):
        if args[:2] == ("release", "download"):
            raise RuntimeError("HTTP 404: stale tag asset")
        if "--jq" in args:
            return "383532078"
        return json.dumps([[{
            "id": 583341386, "name": "ledger.json",
            "state": "uploaded", "size": 512,
        }]])

    monkeypatch.setattr(release_store, "gh", fake_gh)
    with pytest.raises(FileNotFoundError, match="disappeared during deployment"):
        store._download_asset("_tbt_bundle_manifest.json")


def test_stale_release_fallback_does_not_mask_permissions_errors(
    monkeypatch, tmp_path,
):
    import pytest

    store = _store_for_test(tmp_path)
    monkeypatch.setattr(
        release_store, "gh",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("HTTP 403: Forbidden")),
    )
    with pytest.raises(RuntimeError, match="HTTP 403"):
        store._download_asset("feed.json")


def test_upload_checkpoint_recovers_stale_remote_manifest_asset(monkeypatch, tmp_path):
    """The upload path must use the same stale 404 recovery as download()."""
    import json

    store = _store_for_test(tmp_path)
    manifest = json.dumps({
        "schema": 1,
        "files": {
            "history-2025.parquet": {"sha256": "abc", "bytes": 123},
        },
    }).encode()
    store._asset_names = lambda: {store.BUNDLE_MANIFEST}

    def fake_gh(*args):
        if args[:2] == ("release", "download"):
            raise RuntimeError(
                "GitHub CLI operation failed: HTTP 404: Not Found "
                "(https://api.github.com/repos/BackstageTalks/tbt-data/"
                "releases/assets/583058063)"
            )
        if args[0] == "api" and "--jq" in args:
            return "383532078"
        if args[0] == "api" and "--paginate" in args:
            return json.dumps([[{
                "id": 583400001, "name": store.BUNDLE_MANIFEST,
                "state": "uploaded", "size": len(manifest),
            }]])
        raise AssertionError(args)

    def fake_run(cmd, *, stdout, stderr):
        assert str(cmd[-1]).endswith("/assets/583400001")
        stdout.write(manifest)
        return subprocess.CompletedProcess(cmd, 0, None, b"")

    monkeypatch.setattr(release_store, "gh", fake_gh)
    monkeypatch.setattr(release_store.subprocess, "run", fake_run)
    assert store._remote_bundle_files() == {
        "history-2025.parquet": {"sha256": "abc", "bytes": 123}
    }


def test_checkpoint_remote_manifest_403_still_fails_closed(monkeypatch, tmp_path):
    import pytest

    store = _store_for_test(tmp_path)
    store._asset_names = lambda: {store.BUNDLE_MANIFEST}
    monkeypatch.setattr(
        release_store, "gh",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("HTTP 403: Forbidden")),
    )
    with pytest.raises(RuntimeError, match="HTTP 403"):
        store._remote_bundle_files()
