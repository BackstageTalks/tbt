"""Provider-key discovery on already-authorized statistics payloads: no extra API."""
from datetime import datetime, timezone
import json

from tbt.services.statistics_enrichment import StatisticsEnricher


def test_provider_key_inventory_preserves_unknown_postmatch_fields_without_promotion(
        match_factory, tmp_path, monkeypatch):
    monkeypatch.delenv("BLINQ_TENNIS_RAW_CACHE_URL", raising=False)
    monkeypatch.delenv("BLINQ_TENNIS_RAW_CACHE_SQLITE", raising=False)

    class Provider:
        request_count = 0

        def _get(self, path, *, enrichment):
            assert path == "/api/tennis/event/100/statistics" and enrichment
            self.request_count += 1
            return {"statistics": [
                {"period": "ALL", "groups": [{"statisticsItems": [
                    {"key": "aces", "homeValue": 4, "awayValue": 5},
                    {"key": "serviceGamesWon", "home": "2", "away": "3"},
                    {"key": "returnGamesWon", "home": "1", "away": "0"},
                    {"key": "breakPointsConverted", "home": "2/4", "away": "1/2"},
                ]}]},
                {"period": "1ST", "groups": [{"statisticsItems": [
                    {"key": "tieBreaks", "homeValue": 1, "awayValue": 0},
                ]}]},
            ]}

    match = match_factory("match-1", "A", "B", "A")
    match.provider_payload = {
        "_tbt_provider_event_id": "100",
        "_tbt_event_identity": {
            "event_id": "100", "home": "A", "away": "B", "status": "finished",
        },
    }
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path / "stats.sqlite", targeted=True)
    try:
        result = enricher.enrich(match)
        inventory = enricher.statistics_key_summary()
    finally:
        enricher.close()

    assert result == "enriched"
    assert provider.request_count == 1
    assert match.stats["p1_aces"] == 4
    assert match.stats["p2_aces"] == 5
    assert "p1_servicegameswon" not in match.stats
    assert "p1_returngameswon" not in match.stats
    assert inventory["observed_response_payloads"] == 1
    assert inventory["invalid_envelopes"] == 0
    assert inventory["counts_by_key"]["supported"]["aces"] == 1
    assert inventory["counts_by_key"]["supported"]["breakpointsconverted"] == 1
    assert inventory["counts_by_key"]["unsupported"]["servicegameswon"] == 1
    assert inventory["counts_by_key"]["unsupported"]["returngameswon"] == 1
    assert inventory["counts_by_key"]["set_only"]["tiebreaks"] == 1
    serialized = json.dumps(inventory)
    assert "match-1" not in serialized and '"homeValue"' not in serialized


def test_provider_key_inventory_rejects_unbounded_unknown_names(tmp_path, monkeypatch):
    monkeypatch.delenv("BLINQ_TENNIS_RAW_CACHE_URL", raising=False)
    monkeypatch.delenv("BLINQ_TENNIS_RAW_CACHE_SQLITE", raising=False)
    enricher = StatisticsEnricher(object(), tmp_path / "stats.sqlite")
    try:
        enricher._observe_statistics_keys({
            "statistics": [{"period": "ALL", "groups": [{
                "statisticsItems": [
                    {"key": "unknown" + ("x" * 200)},
                    {"key": "ServiceGames"},
                ],
            }]}],
        })
        enricher._observe_statistics_keys({"statistics": []})
        result = enricher.statistics_key_summary()
    finally:
        enricher.close()

    assert result["observed_response_payloads"] == 2
    assert result["invalid_envelopes"] == 0
    assert result["counts_by_key"]["unsupported"] == {"servicegames": 1}
