"""Provider confirmed 2026-10-14: strict event-market and PBP guards."""
from datetime import datetime, timezone

import pytest

from tbt.errors import ProviderError
from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.tennisapi_extra import (
    normalize_market_snapshot, normalize_set_statistics, point_by_point_inventory,
)


SAMPLE = {
    "eventId": 17305441,
    "markets": [
        {"marketId": 1, "marketName": "Full time", "marketPeriod": "Match",
         "isLive": False, "choices": [
             {"name": "1", "initialFractionalValue": "67/100",
              "fractionalValue": "4/5", "change": 1},
             {"name": "2", "initialFractionalValue": "6/5",
              "fractionalValue": "1/1", "change": -1}]},
        {"marketId": 11, "marketName": "First set winner",
         "isLive": False, "choices": [
             {"name": "1", "fractionalValue": "4/5"},
             {"name": "2", "fractionalValue": "1/1"}]},
        {"marketId": 12, "marketName": "Total games won",
         "marketPeriod": "Extra time", "choiceGroup": "22.5",
         "isLive": False, "choices": [
             {"name": "Over", "fractionalValue": "4/5"},
             {"name": "Under", "fractionalValue": "10/11"}]},
        {"marketId": 888, "marketName": "Unconfirmed market",
         "choices": [{"name": "1", "fractionalValue": "4/5"}]},
    ],
}


def test_provider_confirmed_markets_capture_all_and_no_fake_quote_time():
    report = normalize_market_snapshot(
        SAMPLE, event_id="17305441",
        observed_at=datetime(2026, 10, 14, 12, tzinfo=timezone.utc),
    )
    assert report["pre_match_asof_verified"] is False
    assert report["provider_quote_timestamp_known"] is False
    assert report["observed_at_utc"] == "2026-10-14T12:00:00+00:00"
    assert len(report["quotes"]) == 6
    assert {r["market_id"] for r in report["quotes"]} == {1, 11, 12}
    p1 = next(q for q in report["quotes"]
              if q["market_id"] == 1 and q["selection"] == "1")
    assert p1["opening_decimal"] == pytest.approx(1.67)
    assert p1["latest_decimal"] == pytest.approx(1.8)
    total = next(q for q in report["quotes"] if q["market_id"] == 12)
    assert total["line_games"] == 22.5  # not marketPeriod="Extra time"


def test_unavailable_malformed_and_mismatched_markets_fail_closed():
    assert normalize_market_snapshot({}, event_id=1)["quotes"] == []
    with pytest.raises(ProviderError, match="differs"):
        normalize_market_snapshot(SAMPLE, event_id=2)
    with pytest.raises(ProviderError, match="must be a list"):
        normalize_market_snapshot({"markets": {"bad": "shape"}}, event_id=1)
    with pytest.raises(ValueError, match="timezone"):
        normalize_market_snapshot({}, event_id=1, observed_at=datetime(2026, 10, 14))


def test_total_games_requires_line_two_sides_and_valid_prices():
    template = dict(SAMPLE["markets"][2])
    assert normalize_market_snapshot(
        {"markets": [{**template, "choiceGroup": None}]}, event_id=1
    )["quotes"] == []
    assert normalize_market_snapshot(
        {"markets": [{**template, "choices": template["choices"][:1]}]}, event_id=1
    )["quotes"] == []
    assert normalize_market_snapshot(
        {"markets": [{**template, "choices": [
            {"name": "Over", "fractionalValue": "bad"},
            template["choices"][1]]}]}, event_id=1
    )["quotes"] == []


def test_conflicting_repeated_quote_not_silently_selected():
    duplicated = [
        SAMPLE["markets"][0],
        {**SAMPLE["markets"][0], "choices": [
            {"name": "1", "fractionalValue": "1/2"},
            SAMPLE["markets"][0]["choices"][1]]},
    ]
    with pytest.raises(ProviderError, match="Conflicting"):
        normalize_market_snapshot({"markets": duplicated}, event_id=1)


def test_live_set_winner_only_live():
    market = {"marketId": 15, "isLive": False, "choices": [
        {"name": "1", "fractionalValue": "1/1"},
        {"name": "2", "fractionalValue": "1/1"}]}
    assert not normalize_market_snapshot({"markets": [market]}, event_id=1)["quotes"]
    rows = normalize_market_snapshot(
        {"markets": [{**market, "isLive": True}]}, event_id=1
    )["quotes"]
    assert len(rows) == 2 and all(row["is_live"] for row in rows)


def test_set_statistics_reuses_verified_whole_match_fields_without_polluting_all():
    raw = {"statistics": [
        {"period": "ALL", "groups": []},
        {"period": "1ST", "groups": [{"statisticsItems": [
            {"key": "aces", "homeValue": 8, "awayValue": 13},
            {"key": "doubleFaults", "homeValue": 2, "awayValue": 1},
        ]}]},
        {"period": "2ND", "groups": [{"statisticsItems": [
            {"key": "aces", "homeValue": 2, "awayValue": 4},
        ]}]},
    ]}
    parsed = normalize_set_statistics(raw, home_is_player1=False)
    assert parsed["1"]["p2_aces"] == 8
    assert parsed["1"]["p1_aces"] == 13
    assert parsed["1"]["p2_double_faults"] == 2
    assert parsed["2"]["p1_aces"] == 4
    assert len(parsed) == 2
    with pytest.raises(ProviderError, match="Duplicate"):
        normalize_set_statistics(
            {"statistics": [raw["statistics"][1], raw["statistics"][1]]},
            home_is_player1=True,
        )


def test_point_by_point_only_inventory_never_model_features():
    payload = {"eventId": 3, "sets": [{"games": [
        {"score": {"serving": 1, "scoring": 2},
         "points": [{"home": 15, "away": 0}, {"home": 30, "away": 0}]},
        {"score": {"serving": 2, "scoring": 1}, "points": [{}]},
    ]}]}
    result = point_by_point_inventory(payload, event_id=3)
    assert result["points"] == 3
    assert result["games"] == 2
    assert result["games_with_explicit_server"] == 2
    assert result["eligible_for_cdb_point_features"] is False
    assert result["quality_status"] == "structural_only"
    assert point_by_point_inventory({}, event_id=3)["quality_status"] == "unavailable"
    with pytest.raises(ProviderError, match="differs"):
        point_by_point_inventory(payload, event_id=4)
    with pytest.raises(ProviderError, match="points"):
        point_by_point_inventory(
            {"sets": [{"games": [{"points": "corrupted"}]}]},
            event_id=3,
        )


def test_provider_endpoint_paths_and_shared_enrichment_budget(monkeypatch):
    client = object.__new__(RapidTennisClient)
    paths = []

    def fake_get(path, params=None, *, enrichment=False):
        paths.append((path, enrichment))
        return {"sets": []} if path.endswith("point-by-point") else SAMPLE

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.event_point_by_point(55) == {"sets": []}
    assert client.event_markets_snapshot(17305441)["quotes"][0]["market_id"] == 1
    assert paths == [
        ("/api/tennis/event/55/point-by-point", True),
        ("/api/tennis/event/17305441/odds/1/all", True),
    ]


def test_enrichment_reuses_paid_statistics_and_stores_provider_side_sets(
        match_factory, tmp_path):
    from tbt.services.statistics_enrichment import StatisticsEnricher

    class Provider:
        calls = []

        def _get(self, path, **kwargs):
            self.calls.append(path)
            if path.endswith("/statistics"):
                return {"statistics": [
                    {"period": "ALL", "groups": [{"statisticsItems": [
                        {"key": "aces", "homeValue": 10, "awayValue": 20},
                    ]}]},
                    {"period": "1ST", "groups": [{"statisticsItems": [
                        {"key": "aces", "homeValue": 3, "awayValue": 9},
                    ]}]},
                    {"period": "2ND", "groups": [{"statisticsItems": [
                        {"key": "aces", "homeValue": 7, "awayValue": 11},
                    ]}]},
                ]}
            return {"event": {
                "homeTeam": {"id": "B"}, "awayTeam": {"id": "A"},
                "status": {"type": "finished"},
            }}

    provider = Provider()
    match = match_factory("x", "A", "B", "A")
    match.provider_payload = {"id": "17305441"}
    enricher = StatisticsEnricher(provider, tmp_path / "per_set.sqlite")
    try:
        assert enricher.enrich(match) == "enriched"
        assert match.stats["p1_aces"] == 20
        assert match.stats["p2_aces"] == 10
        per_set = match.provider_payload["_tbt_statistics_by_set"]
        assert per_set["orientation"] == "provider_home_away"
        assert per_set["scope"] == "post_match_only"
        assert per_set["sets"]["1"]["home_aces"] == 3
        assert per_set["sets"]["1"]["away_aces"] == 9
        # Player order in canonical history can change without modifying
        # source-side (home/away) per-set evidence.
        assert match.swapped().provider_payload["_tbt_statistics_by_set"] == per_set
        assert len(provider.calls) == 2
    finally:
        enricher.close()


def test_invalid_per_set_totals_never_override_valid_whole_match(
        match_factory, tmp_path):
    from tbt.services.statistics_enrichment import StatisticsEnricher

    class Provider:
        def _get(self, path, **kwargs):
            if path.endswith("/statistics"):
                return {"statistics": [
                    {"period": "ALL", "groups": [{"statisticsItems": [
                        {"key": "aces", "homeValue": 2, "awayValue": 1},
                    ]}]},
                    {"period": "1ST", "groups": [{"statisticsItems": [
                        {"key": "aces", "homeValue": 9, "awayValue": 1},
                    ]}]},
                ]}
            return {"event": {
                "homeTeam": {"id": "A"}, "awayTeam": {"id": "B"},
                "status": {"type": "finished"},
            }}

    match = match_factory("x", "A", "B", "A")
    match.provider_payload = {"id": "123"}
    enricher = StatisticsEnricher(Provider(), tmp_path / "per_set_bad.sqlite")
    try:
        assert enricher.enrich(match) == "enriched"
        assert match.stats["p1_aces"] == 2
        assert "_tbt_statistics_by_set" not in match.provider_payload
    finally:
        enricher.close()
