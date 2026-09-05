from dataclasses import replace

import pytest

from tbt.errors import ProviderError
from tbt.providers.statistics import parse_statistics
from tbt.services.statistics_enrichment import StatisticsEnricher
from tbt.models.feature_builder import FeatureBuilder
from tbt.data.history_snapshot import load_snapshot, write_snapshot


def payload():
    return {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        {"name": "1st serve points", "home": "80% (40/50)", "away": "60% (30/50)"},
        {"name": "2nd serve points", "homeValue": 5, "homeTotal": 10, "awayValue": 10, "awayTotal": 20},
    ]}]}]}


def test_rates_are_weighted_and_attached_to_correct_side():
    stats = parse_statistics(payload(), home_is_player1=False)
    assert stats["p2_service_points_won"] == .75
    assert stats["p1_return_points_won"] == .25
    assert stats["p1_service_points_won"] == 40 / 70
    assert FeatureBuilder._extract_quality(stats, "p2") == (.75, 1 - 40 / 70)


def test_set_statistics_never_override_whole_match():
    raw = payload()
    raw["statistics"].append({"period": "1", "groups": [{"statisticsItems": [
        {"name": "1st serve points", "home": "1%", "away": "99%"}]}]})
    assert parse_statistics(raw, home_is_player1=True)["p1_first_serve_win"] == .8


def test_unknown_and_missing_are_not_zero():
    assert parse_statistics({}, home_is_player1=True) == {}
    with pytest.raises(ProviderError):
        parse_statistics({"statistics": [{"period": "1"}]}, home_is_player1=True)
    raw = payload()
    raw["statistics"][0]["groups"][0]["statisticsItems"] = [{"name": "service points won", "home": "40"}]
    with pytest.raises(ProviderError):
        parse_statistics(raw, home_is_player1=True)


def test_enrichment_cache_identity_and_parquet_roundtrip(match_factory, tmp_path):
    class Provider:
        calls = 0
        def _get(self, path, **kwargs):
            self.calls += 1
            if path.endswith("statistics"):
                return payload()
            return {"event": {"homeTeam": {"id": "B"}, "awayTeam": {"id": "A"}, "status": {"type": "finished"}}}
    provider = Provider()
    match = match_factory("a", "A", "B", "B")
    match.provider_payload = {"id": "123"}
    enricher = StatisticsEnricher(provider, tmp_path / "cache.sqlite")
    assert enricher.enrich(match) == "enriched"
    assert enricher.enrich(match) == "cached"
    assert provider.calls == 2
    path = tmp_path / "history.parquet"
    write_snapshot([match], path)
    restored = load_snapshot(path)[0]
    assert restored.stats == match.stats
    assert enricher.enrich(restored) == "cached"
    bad = replace(match, player1_id="C", provider_payload={"id": "123"})
    with pytest.raises(ProviderError, match="identity"):
        enricher.enrich(bad)
    enricher.close()


def test_same_day_statistics_cannot_predict_another_same_day_match(match_factory):
    first = match_factory("a", "A", "B", "A", day=1)
    first.stats = parse_statistics(payload(), home_is_player1=True)
    second = match_factory("b", "A", "B", "B", day=1)
    third = match_factory("c", "A", "B", "A", day=2)
    frame = FeatureBuilder().build_training_frame([first, second, third])
    assert frame.iloc[0].stats_known_both == 0
    assert frame.iloc[1].stats_known_both == 0
    assert frame.iloc[2].stats_known_both == 1


def test_verified_calendar_identity_saves_detail_request_across_runs(match_factory, tmp_path):
    class Provider:
        calls = []
        def _get(self, path, **kwargs):
            self.calls.append(path)
            assert path.endswith('/statistics')
            return payload()
    provider = Provider()
    match = match_factory('a', 'A', 'B', 'A')
    match.provider_payload = {'id': '123', '_tbt_event_identity': {
        'event_id': '123', 'home': 'A', 'away': 'B', 'status': 'finished'}}
    path = tmp_path / 'history.parquet'
    write_snapshot([match], path)
    match = load_snapshot(path)[0]
    enricher = StatisticsEnricher(provider, tmp_path / 'cache.sqlite')
    assert enricher.enrich(match) == 'enriched'
    match.provider_payload['_tbt_statistics']['fetched_at'] = '2020-01-01T00:00:00+00:00'
    assert enricher.enrich(match) == 'cached'
    assert len(provider.calls) == 1
    enricher.close()
