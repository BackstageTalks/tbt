from __future__ import annotations

import json

import pytest

import tbt.services.feed as feed_service


def test_serving_feed_cap_allows_current_release_size(tmp_path):
    assert feed_service.MAX_FEED_BYTES == 20 * 1024 * 1024
    # The 2026-10-12 verified published candidate is 16,901,251 bytes.
    # Keep enough space for this immutable snapshot without removing size protection.
    assert 16_901_251 < feed_service.MAX_FEED_BYTES


def test_serving_feed_size_cap_is_still_enforced(monkeypatch, tmp_path):
    path = tmp_path / "feed.json"
    payload = feed_service.empty_feed()
    payload["padding"] = "x" * 2048
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(feed_service, "MAX_FEED_BYTES", 1024)
    with pytest.raises(ValueError, match="Serving feed exceeds"):
        feed_service.read_feed(path)
