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
