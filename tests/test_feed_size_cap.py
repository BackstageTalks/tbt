from __future__ import annotations

import json

import pytest

import tbt.services.feed as feed_service


def test_serving_feed_cap_allows_current_release_size(tmp_path):
    assert feed_service.MAX_FEED_BYTES == 32 * 1024 * 1024
    # The 2026-10-25 morning candidate was generated and persisted with this
    # exact size, but packaging aborted against the obsolete 20 MiB cap.
    assert 21_728_761 < feed_service.MAX_FEED_BYTES
    # Keep a finite protection boundary: do not silently accept runaway output.
    assert feed_service.MAX_FEED_BYTES <= 32 * 1024 * 1024


def test_serving_feed_size_cap_is_still_enforced(monkeypatch, tmp_path):
    path = tmp_path / "feed.json"
    payload = feed_service.empty_feed()
    payload["padding"] = "x" * 2048
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(feed_service, "MAX_FEED_BYTES", 1024)
    with pytest.raises(ValueError, match="Serving feed exceeds"):
        feed_service.read_feed(path)


def test_serving_feed_rejects_payload_even_one_byte_over_cap(tmp_path):
    path = tmp_path / "oversized-feed.json"
    # Sparse file: exercise the size gate without allocating 32 MiB in RAM.
    with path.open("wb") as handle:
        handle.truncate(feed_service.MAX_FEED_BYTES + 1)
    with pytest.raises(ValueError, match="Serving feed exceeds the 32 MB cap"):
        feed_service.read_feed(path)
