"""Offline safety tests for the optional charting reader."""
import gzip
import json
from unittest.mock import patch

import pytest

from tbt.data.charting_client import ChartingClient, ChartingUnavailable


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, count):
        return self.body[:count]


def test_disabled_without_token():
    with patch.dict("os.environ", {}, clear=True):
        client = ChartingClient()
        with pytest.raises(ChartingUnavailable, match="not configured"):
            client.manifest()


def test_manifest_cached_without_second_request():
    payload = json.dumps({"schema_version": 1, "player_count": 1742}).encode()
    with patch("tbt.data.charting_client.urlopen", return_value=FakeResponse(payload)) as fetch:
        client = ChartingClient(token="test-token")
        assert client.manifest()["player_count"] == 1742
        assert client.manifest()["player_count"] == 1742
        assert fetch.call_count == 1


def test_profile_rejects_traversal_without_network():
    client = ChartingClient(token="test-token")
    with pytest.raises(ValueError):
        client.profile("../../private.json.gz")
    with pytest.raises(ValueError):
        client.profile("profiles/wta/atp-example.json.gz")


def test_gzip_profile():
    payload = gzip.compress(json.dumps({"player_id": "wta-test"}).encode())
    with patch("tbt.data.charting_client.urlopen", return_value=FakeResponse(payload)):
        result = ChartingClient(token="test-token").profile("profiles/wta/wta-test.json.gz")
        assert result["player_id"] == "wta-test"


def test_invalid_manifest():
    with patch("tbt.data.charting_client.urlopen", return_value=FakeResponse(b'{"schema_version": 99}')):
        with pytest.raises(ChartingUnavailable, match="Unsupported"):
            ChartingClient(token="test-token").manifest()
