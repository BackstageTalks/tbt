from dataclasses import replace
from datetime import datetime, timezone

import pytest

from tbt.errors import ProviderError
from tbt.providers.statistics import parse_statistics, complete_opponent_service_rates
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




def test_valid_statistics_with_only_unsupported_fields_is_cached_as_unavailable(match_factory, tmp_path):
    class Provider:
        calls = []
        def _get(self, path, **kwargs):
            self.calls.append(path)
            if path.endswith("/statistics"):
                return {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
                    {"name": "Games won", "home": "12", "away": "9"},
                    {"key": "totalPointsWon", "home": "67", "away": "61"},
                ]}]}]}
            return {"event": {
                "homeTeam": {"id": "A"}, "awayTeam": {"id": "B"},
                "status": {"type": "finished"},
            }}

    provider = Provider()
    match = match_factory("a", "A", "B", "A")
    match.provider_payload = {"id": "123"}
    enricher = StatisticsEnricher(provider, tmp_path / "unsupported.sqlite")

    assert enricher.enrich(match) == "unavailable"
    marker = match.provider_payload["_tbt_statistics"]
    assert marker["status"] == "unavailable"
    assert marker["reason"] == "no_supported_fields"
    assert marker["unsupported_keys"] == ["Games won", "totalPointsWon"]
    assert match.stats == {}

    # A canonical unavailable marker is retried monthly, not on every run.
    assert enricher.enrich(match) == "cached"
    assert provider.calls == ["/api/tennis/event/123", "/api/tennis/event/123/statistics"]
    enricher.close()


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


def test_aces_and_double_faults_are_raw_counts_not_rates():
    raw = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        {"name": "Aces", "home": "11", "awayValue": 4},
        {"key": "doubleFaults", "homeValue": 2, "away": "5"},
    ]}]}]}
    stats = parse_statistics(raw, home_is_player1=False)
    assert stats["p2_aces"] == 11
    assert stats["p1_aces"] == 4
    assert stats["p2_double_faults"] == 2
    assert stats["p1_double_faults"] == 5


def test_statistics_schema_one_is_revisited_for_new_count_contract(match_factory, tmp_path):
    class Provider:
        calls = []
        def _get(self, path, **kwargs):
            self.calls.append(path)
            return {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
                {"name": "Aces", "home": "8", "away": "3"},
                {"name": "Double faults", "home": "2", "away": "4"},
            ]}]}]}
    match = match_factory("a", "A", "B", "A")
    match.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {"event_id": "123", "home": "A", "away": "B", "status": "finished"},
        "_tbt_statistics": {
            "schema": 1, "event_id": "123", "source": "tennisapi1",
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "available",
        },
    }
    enricher = StatisticsEnricher(Provider(), tmp_path / "schema2.sqlite")
    assert enricher.enrich(match) == "enriched"
    assert match.stats["p1_aces"] == 8
    assert match.stats["p2_double_faults"] == 4
    assert match.provider_payload["_tbt_statistics"]["schema"] == 3
    assert enricher.enrich(match) == "cached"
    enricher.close()


def _tennisapi_rate_sample():
    # Real ALL-period item keys/counts captured by the 2026-09-23 provider probe.
    items = [
        {"key": "aces", "homeValue": 5, "awayValue": 0},
        {"key": "doubleFaults", "homeValue": 4, "awayValue": 3},
        {"key": "firstServeAccuracy", "homeValue": 45, "homeTotal": 64,
         "awayValue": 42, "awayTotal": 67},
        {"key": "secondServeAccuracy", "homeValue": 15, "homeTotal": 19,
         "awayValue": 22, "awayTotal": 25},
        {"key": "firstServePointsAccuracy", "homeValue": 31, "homeTotal": 45,
         "awayValue": 27, "awayTotal": 42},
        {"key": "secondServePointsAccuracy", "homeValue": 8, "homeTotal": 19,
         "awayValue": 9, "awayTotal": 25},
        {"key": "firstReturnPoints", "homeValue": 15, "homeTotal": 42,
         "awayValue": 14, "awayTotal": 45},
        {"key": "secondReturnPoints", "homeValue": 16, "homeTotal": 25,
         "awayValue": 11, "awayTotal": 19},
    ]
    return {"statistics": [
        {"period": "ALL", "groups": [{"statisticsItems": items}]},
        {"period": "1ST", "groups": [{"statisticsItems": [
            {"key": "firstServePointsAccuracy", "homeValue": 1, "homeTotal": 10},
        ]}]},
    ]}


def test_real_tennisapi_rates_are_weighted_and_serve_placement_is_not_quality():
    stats = parse_statistics(_tennisapi_rate_sample(), home_is_player1=True)
    assert stats["p1_first_serve_win"] == 31 / 45
    assert stats["p1_second_serve_win"] == 8 / 19
    assert stats["p1_service_points_won"] == 39 / 64
    assert stats["p2_service_points_won"] == 36 / 67
    assert stats["p1_return_points_won"] == 31 / 67
    assert stats["p2_return_points_won"] == 25 / 64
    assert stats["p1_aces"] == 5 and stats["p2_double_faults"] == 3
    assert "p1_first_serve_in" not in stats
    assert FeatureBuilder._extract_quality(stats, "p1") == (39 / 64, 31 / 67)


def test_tennisapi_rates_follow_verified_home_away_orientation():
    stats = parse_statistics(_tennisapi_rate_sample(), home_is_player1=False)
    assert stats["p2_service_points_won"] == 39 / 64
    assert stats["p2_return_points_won"] == 31 / 67
    assert stats["p1_service_points_won"] == 36 / 67
    assert stats["p1_return_points_won"] == 25 / 64


def test_first_serve_placement_alone_never_becomes_serve_quality():
    raw = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        {"key": "firstServeAccuracy", "homeValue": 45, "homeTotal": 64,
         "awayValue": 42, "awayTotal": 67},
        {"key": "secondServeAccuracy", "homeValue": 15, "homeTotal": 19,
         "awayValue": 22, "awayTotal": 25},
    ]}]}]}
    with pytest.raises(ProviderError):
        parse_statistics(raw, home_is_player1=True)


def test_schema_two_count_only_marker_is_retried_for_quality_rates(match_factory, tmp_path):
    class Provider:
        calls = []
        def _get(self, path, **kwargs):
            self.calls.append(path)
            assert path.endswith("/statistics")
            return _tennisapi_rate_sample()

    match = match_factory("old", "A", "B", "A")
    match.stats = {"p1_aces": 5.0, "p2_aces": 0.0}
    match.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "home": "A", "away": "B", "status": "finished"
        },
        "_tbt_statistics": {
            "schema": 2, "event_id": "123", "source": "tennisapi1",
            "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "available",
        },
    }
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path / "schema3.sqlite")
    assert enricher.enrich(match) == "enriched"
    assert match.stats["p1_service_points_won"] == 39 / 64
    assert match.stats["p1_return_points_won"] == 31 / 67
    assert match.provider_payload["_tbt_statistics"]["schema"] == 3
    assert enricher.enrich(match) == "cached"
    assert provider.calls == ["/api/tennis/event/123/statistics"]
    enricher.close()


def test_return_only_quality_recovers_both_service_rates_without_serve_fields():
    raw = {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        {"key": "firstReturnPoints", "homeValue": 15, "homeTotal": 42,
         "awayValue": 14, "awayTotal": 45},
        {"key": "secondReturnPoints", "homeValue": 16, "homeTotal": 25,
         "awayValue": 11, "awayTotal": 19},
    ]}]}]}
    stats = parse_statistics(raw, home_is_player1=True)
    assert stats["p1_return_points_won"] == 31 / 67
    assert stats["p2_return_points_won"] == 25 / 64
    assert stats["p1_service_points_won"] == 39 / 64
    assert stats["p2_service_points_won"] == 36 / 67
    assert FeatureBuilder._extract_quality(stats, "p1") == (39 / 64, 31 / 67)


def test_derived_service_never_overwrites_explicit_or_uses_invalid_return():
    stats = {"p1_service_points_won": 0.7, "p2_return_points_won": 0.4,
             "p1_return_points_won": 1.4}
    assert not complete_opponent_service_rates(stats)
    assert stats["p1_service_points_won"] == 0.7
    assert "p2_service_points_won" not in stats


def test_existing_return_only_schema_three_repairs_without_api_calls(match_factory, tmp_path):
    class NoRequests:
        def _get(self, path, **kwargs):
            raise AssertionError(f"Local repair must not call provider: {path}")

    match = match_factory("return-only", "A", "B", "A")
    match.stats = {"p1_return_points_won": 31 / 67,
                   "p2_return_points_won": 25 / 64}
    match.provider_payload = {
        "id": "123",
        "_tbt_statistics": {
            "schema": 3, "event_id": "123", "source": "tennisapi1",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status": "available",
        },
    }
    enricher = StatisticsEnricher(NoRequests(), tmp_path / "local-repair.sqlite")
    assert enricher.enrich(match) == "enriched"
    assert match.stats["p1_service_points_won"] == 39 / 64
    assert match.stats["p2_service_points_won"] == 36 / 67
    assert enricher.enrich(match) == "cached"
    enricher.close()
