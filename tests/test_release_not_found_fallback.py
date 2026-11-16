from unittest.mock import patch

import pytest

from scripts.release_store import ReleaseStore


def test_release_not_found_uses_authenticated_asset_id_fallback(tmp_path):
    store = object.__new__(ReleaseStore)
    store.repository = "BackstageTalks/tbt-data"
    store.tag = "tbt-data-v1"
    store.directory = tmp_path
    with patch("scripts.release_store.gh", side_effect=RuntimeError(
        "GitHub CLI operation failed: release not found"
    )), patch.object(store, "_download_current_asset_after_stale_404") as fallback:
        store._download_asset("history-2026.parquet")
    fallback.assert_called_once_with("history-2026.parquet")


@pytest.mark.parametrize("error", [
    "GitHub CLI operation failed: HTTP 403: Resource not accessible",
    "GitHub CLI operation failed: HTTP 429: rate limit",
    "GitHub CLI operation failed: bad credentials",
])
def test_release_download_other_failures_stay_closed(tmp_path, error):
    store = object.__new__(ReleaseStore)
    store.repository = "BackstageTalks/tbt-data"
    store.tag = "tbt-data-v1"
    store.directory = tmp_path
    with patch("scripts.release_store.gh", side_effect=RuntimeError(error)), patch.object(
        store, "_download_current_asset_after_stale_404"
    ) as fallback:
        with pytest.raises(RuntimeError, match="GitHub CLI operation failed"):
            store._download_asset("history-2026.parquet")
    fallback.assert_not_called()


def test_asset_names_uses_fresh_authenticated_release_id_inventory(monkeypatch, tmp_path):
    # Production incident 43833898190: gh release view reported "release not
    # found" despite a valid release tag and 121 canonical release assets.
    # The journal must use the same paginated REST inventory as the guarded
    # publisher; never interpret the stale view as a release creation.
    from scripts import release_store

    store = object.__new__(ReleaseStore)
    store.repository = "BackstageTalks/tbt-data"
    store.tag = "tbt-data-v1"
    store.directory = tmp_path

    def stale_view(*_args, **_kwargs):
        raise AssertionError("Never call stale gh release view")

    monkeypatch.setattr(release_store, "gh", stale_view)
    monkeypatch.setattr(store, "_release_asset_inventory", lambda: {
        "history_manifest.json": {"name": "history_manifest.json", "id": 12},
        "history-2026.parquet": {"name": "history-2026.parquet", "id": 13},
    })
    assert store._asset_names() == {
        "history_manifest.json", "history-2026.parquet",
    }


def test_asset_names_fails_closed_if_rest_release_inventory_unavailable(monkeypatch, tmp_path):
    store = object.__new__(ReleaseStore)
    store.repository = "BackstageTalks/tbt-data"
    store.tag = "tbt-data-v1"
    store.directory = tmp_path

    def denied():
        raise RuntimeError("REST release ID lookup: HTTP 403")

    monkeypatch.setattr(store, "_release_asset_inventory", denied)
    with pytest.raises(RuntimeError, match="403"):
        store._asset_names()
