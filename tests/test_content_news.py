import json
from datetime import datetime, timezone

from tbt.services import content_news


RSS_A = b'''<?xml version="1.0"?><rss><channel>
<item><title>Fresh tennis story</title><link>https://tennis.example/story</link><pubDate>Sun, 06 Sep 2026 17:00:00 GMT</pubDate></item>
<item><title>Old tennis story</title><link>https://tennis.example/old</link><pubDate>Mon, 31 Aug 2026 17:00:00 GMT</pubDate></item>
</channel></rss>'''
RSS_B = b'''<?xml version="1.0"?><rss><channel>
<item><title>Fresh tennis story</title><link>https://other.example/duplicate-title</link><pubDate>Sun, 06 Sep 2026 18:00:00 GMT</pubDate></item>
<item><title>Second fresh story</title><link>https://other.example/second</link><pubDate>Sun, 06 Sep 2026 18:30:00 GMT</pubDate></item>
</channel></rss>'''


class FakeResponse:
    def __init__(self, content):
        self.status_code = 200
        self.content = content


class FakeClient:
    def get(self, url):
        return FakeResponse(RSS_A if "one" in url else RSS_B)


def test_multiple_rss_sources_are_deduped_and_stale_items_are_filtered(tmp_path, monkeypatch):
    cfg = {
        "schema": 1,
        "rss": {
            "enabled": True,
            "refresh_minutes": 45,
            "max_age_hours": 48,
            "max_items": 24,
            "sources": [
                {"name": "One", "url": "https://feed.example/one", "priority": 10},
                {"name": "Two", "url": "https://feed.example/two", "priority": 8},
            ],
        },
    }
    path = tmp_path / "content.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(content_news, "CONFIG", path)
    content_news._CACHE["expires"] = 0.0
    content_news._CACHE["items"] = []

    result = content_news.news_pool(
        client=FakeClient(),
        now=datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc),
    )
    assert result["sources"] == 2
    assert [item["title"] for item in result["items"]] == [
        "Fresh tennis story",
        "Second fresh story",
    ]
    assert all(item["title"] != "Old tennis story" for item in result["items"])


def test_invalid_or_disabled_sources_do_not_trigger_requests(tmp_path, monkeypatch):
    cfg = {"rss": {"enabled": True, "sources": [
        {"name": "Bad", "url": "file:///etc/passwd"},
        {"name": "Off", "url": "https://feed.example/off", "enabled": False},
    ]}}
    path = tmp_path / "content.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(content_news, "CONFIG", path)
    content_news._CACHE["expires"] = 0.0
    content_news._CACHE["items"] = []

    class FailClient:
        def get(self, url):
            raise AssertionError("No request expected")

    result = content_news.news_pool(client=FailClient(), now=datetime.now(timezone.utc))
    assert result["items"] == []
    assert result["sources"] == 0


def test_runtime_ui_config_can_supply_rss_sources_without_editing_backend_file(monkeypatch):
    content_news._CACHE["expires"] = 0.0
    content_news._CACHE["items"] = []
    runtime = {
        "rss": {
            "enabled": True,
            "refresh_minutes": 60,
            "max_age_hours": 48,
            "max_items": 24,
            "sources": [
                {"id": "main", "name": "Runtime", "url": "https://feed.example/one", "priority": 10, "enabled": True},
            ],
        }
    }
    result = content_news.news_pool(
        client=FakeClient(),
        now=datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc),
        config=runtime,
    )
    assert result["sources"] == 1
    assert result["items"][0]["source"] == "Runtime"
