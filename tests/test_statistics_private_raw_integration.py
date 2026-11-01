"""StatisticsEnricher opt-in raw-cache read-through across separate runner instances."""
from types import SimpleNamespace

from tbt.services.statistics_enrichment import StatisticsEnricher


def test_enricher_uses_shared_private_cache_between_jobs(tmp_path, monkeypatch):
    private_path = tmp_path / "private-provider-raw.sqlite"
    monkeypatch.setenv("BLINQ_TENNIS_RAW_CACHE_SQLITE", str(private_path))
    calls = []
    class Provider:
        cfg = SimpleNamespace(rapidapi_host="tennisapi1.p.rapidapi.com")
        def _get(self, path, *, enrichment=False):
            calls.append(path)
            return {"statistics": [{"period": "ALL", "groups": [
                {"statisticsItems": [{"key": "aces", "home": "2", "away": "3"}]}
            ]}]}
    first = StatisticsEnricher(Provider(), tmp_path / "runner-a.sqlite")
    payload = first._get("/api/tennis/event/7115726/statistics", max_age=86400)
    first.close()
    second = StatisticsEnricher(Provider(), tmp_path / "runner-b.sqlite")
    assert second._get("/api/tennis/event/7115726/statistics", max_age=86400) == payload
    second.close()
    assert calls == ["/api/tennis/event/7115726/statistics"]


def test_enricher_fails_closed_for_missing_configured_private_mount(tmp_path, monkeypatch):
    monkeypatch.setenv("BLINQ_TENNIS_RAW_CACHE_SQLITE", str(tmp_path / "missing" / "raw.sqlite"))
    from tbt.services.tennis_response_cache import RawCacheUnavailable
    import pytest
    class Provider:
        cfg = SimpleNamespace(rapidapi_host="tennisapi1.p.rapidapi.com")
    with pytest.raises(RawCacheUnavailable):
        StatisticsEnricher(Provider(), tmp_path / "scratch.sqlite")
