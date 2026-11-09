"""Offline extraction of whole-match point counts from an already-paid TennisApi response."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tbt.errors import ProviderError
from tbt.providers.statistics import inventory_statistics_keys, parse_statistics
from tbt.services.statistics_enrichment import StatisticsEnricher


def sample():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "tennisapi_stats_14232981_minimal.json")
        .read_text(encoding="utf-8")
    )


def all_counts(*, home_service=30, away_service=37, home_receive=19, away_receive=29,
               home_total=49, away_total=66):
    return {"statistics": [{"period": "ALL", "groups": [{"statisticsItems": [
        {"key": "servicePointsScored", "homeValue": home_service,
         "awayValue": away_service},
        {"key": "receiverPointsScored", "homeValue": home_receive,
         "awayValue": away_receive},
        {"key": "pointsTotal", "homeValue": home_total, "awayValue": away_total},
        {"key": "aces", "homeValue": 6, "awayValue": 4},
    ]}]}]}


@pytest.mark.parametrize("home_is_player1", [True, False])
def test_existing_all_fixture_produces_eight_conserved_rate_and_total_cells(home_is_player1):
    payload = sample()
    before = json.dumps(payload, sort_keys=True)
    stats = parse_statistics(payload, home_is_player1=home_is_player1)
    home, away = ("p1", "p2") if home_is_player1 else ("p2", "p1")
    assert stats[f"{home}_service_points_won"] == pytest.approx(30 / 59)
    assert stats[f"{away}_return_points_won"] == pytest.approx(29 / 59)
    assert stats[f"{away}_service_points_won"] == pytest.approx(37 / 56)
    assert stats[f"{home}_return_points_won"] == pytest.approx(19 / 56)
    assert stats[f"{home}_service_points_total"] == 59
    assert stats[f"{away}_return_points_total"] == 59
    assert stats[f"{away}_service_points_total"] == 56
    assert stats[f"{home}_return_points_total"] == 56
    assert stats[f"{home}_aces"] == 6
    assert json.dumps(payload, sort_keys=True) == before
    inventory = inventory_statistics_keys(payload)
    assert {"pointstotal", "servicepointsscored", "receiverpointsscored"} <= set(
        inventory["supported"]
    )
    assert not {"pointstotal", "servicepointsscored", "receiverpointsscored"} & set(
        inventory["unsupported"]
    )


def test_internally_inconsistent_total_won_skips_point_derived_cells_not_aces():
    payload = all_counts(home_total=50)  # 30 service + 19 receive = 49
    stats = parse_statistics(payload, home_is_player1=True)
    assert stats == {"p1_aces": 6.0, "p2_aces": 4.0}


@pytest.mark.parametrize("bad_value", [True, -1, 3.5, "3/5", "99%", float("inf")])
def test_unsupported_point_count_never_converts_to_ratio(bad_value):
    payload = all_counts(home_service=bad_value)
    stats = parse_statistics(payload, home_is_player1=True)
    assert stats == {"p1_aces": 6.0, "p2_aces": 4.0}


def test_missing_or_duplicate_conflicting_counts_fail_closed_without_partial_rates():
    payload = all_counts()
    items = payload["statistics"][0]["groups"][0]["statisticsItems"]
    del items[1]["awayValue"]
    assert parse_statistics(payload, home_is_player1=True) == {
        "p1_aces": 6.0, "p2_aces": 4.0,
    }
    payload = all_counts()
    payload["statistics"][0]["groups"][0]["statisticsItems"].append({
        "key": "servicePointsScored", "homeValue": 31, "awayValue": 37,
    })
    assert parse_statistics(payload, home_is_player1=True) == {
        "p1_aces": 6.0, "p2_aces": 4.0,
    }


def test_explicit_whole_match_rate_disagreement_quarantines_entire_response():
    payload = all_counts()
    payload["statistics"][0]["groups"][0]["statisticsItems"].append({
        "key": "servicePointsWon", "homeValue": 3, "homeTotal": 5,
    })
    with pytest.raises(ProviderError, match="Conflicting whole-match statistic"):
        parse_statistics(payload, home_is_player1=True)


class Provider:
    def __init__(self):
        self.calls = 0

    def _get(self, path, **kwargs):
        assert path == "/api/tennis/event/123/statistics"
        assert kwargs.get("enrichment") is True
        self.calls += 1
        return sample()


def test_native_enricher_preserves_nonnull_and_only_adds_verified_missing_cells(
    match_factory, tmp_path
):
    match = match_factory("whole-point-count", "A", "B", "A")
    match.scheduled_at = datetime(2024, 1, 10, 12, tzinfo=timezone.utc)
    existing = 30 / 59 + 5e-11
    match.stats = {"p1_service_points_won": existing, "p1_aces": 6}
    match.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "home": "A", "away": "B", "status": "finished",
        },
    }
    provider = Provider()
    enricher = StatisticsEnricher(
        provider, tmp_path / "count.sqlite", targeted=True, break_points_focus=True
    )
    try:
        assert enricher.enrich(match) == "enriched"
        assert provider.calls == 1
        assert match.stats["p1_service_points_won"] == existing
        assert match.stats["p1_aces"] == 6
        assert match.stats["p2_return_points_won"] == pytest.approx(29 / 59)
        assert match.stats["p1_service_points_total"] == 59
        assert match.stats["p2_return_points_total"] == 59
        assert match.stats["p2_service_points_total"] == 56
        assert match.stats["p1_return_points_total"] == 56
        assert enricher.enrich(match) == "cached"
        assert provider.calls == 1
    finally:
        enricher.close()


def test_canonical_rate_conflict_keeps_whole_provider_response_out_of_cdb(
    match_factory, tmp_path
):
    match = match_factory("whole-point-quarantine", "A", "B", "A")
    match.scheduled_at = datetime(2024, 1, 10, 12, tzinfo=timezone.utc)
    before = {"p1_service_points_won": 0.75, "p1_aces": 6}
    match.stats = dict(before)
    match.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "home": "A", "away": "B", "status": "finished",
        },
    }
    provider = Provider()
    enricher = StatisticsEnricher(
        provider, tmp_path / "quarantine.sqlite", targeted=True, break_points_focus=True
    )
    try:
        assert enricher.enrich(match) == "conflict"
        assert provider.calls == 1
        assert match.stats == before
        assert match.provider_payload["_tbt_statistics"]["status"] == "conflict"
        assert enricher.conflict_diagnostics()["rejected_responses"] == 1
    finally:
        enricher.close()
