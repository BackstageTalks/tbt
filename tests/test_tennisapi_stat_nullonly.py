"""Strict NULL-only provider enrichment; no paid provider or canonical CDB I/O."""
from datetime import datetime, timezone

import pytest

from tbt.services.statistics_enrichment import StatisticsEnricher


class Provider:
    def __init__(self, *, ace_value=7):
        self.calls = 0
        self.ace_value = ace_value

    def _get(self, path, **kwargs):
        assert path == "/api/tennis/event/123/statistics"
        assert kwargs.get("enrichment") is True
        self.calls += 1
        return {"statistics": [{"period": "ALL", "groups": [
            {"statisticsItems": [
                {"key": "servicePointsWon", "homeValue": 3, "homeTotal": 5},
                {"key": "aces", "homeValue": self.ace_value},
                {"key": "breakPointsSaved",
                 "homeValue": 3, "homeTotal": 5,
                 "awayValue": 4, "awayTotal": 6},
                {"key": "breakPointsScored", "homeValue": 2, "awayValue": 2},
            ]}
        ]}]}


def match_with_verified_id(match_factory, existing):
    m = match_factory("nullonly-provider", "A", "B", "A")
    m.scheduled_at = datetime(2024, 1, 10, 12, tzinfo=timezone.utc)
    m.stats = dict(existing)
    m.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "home": "A", "away": "B", "status": "finished",
        },
    }
    return m


def test_numerically_equivalent_rate_preserves_original_value_and_fills_only_null(
        match_factory, tmp_path):
    original = 0.60000000005
    m = match_with_verified_id(
        match_factory, {"p1_service_points_won": original, "p1_aces": 7})
    before = dict(m.stats)
    provider = Provider()
    e = StatisticsEnricher(provider, tmp_path / "rate.sqlite",
                           targeted=True, break_points_focus=True)
    try:
        assert e.enrich(m) == "enriched"
        assert provider.calls == 1
        assert m.stats["p1_service_points_won"] == original
        assert m.stats["p1_aces"] == before["p1_aces"]
        assert m.stats["p1_break_point_return_win"] == pytest.approx(2 / 6)
        assert m.stats["p2_break_point_return_win"] == pytest.approx(2 / 5)
        assert m.stats["p2_return_points_won"] == pytest.approx(0.4)
        d = e.conflict_diagnostics()
        assert d["rejected_responses"] == 0
        assert d["equivalent_numeric_fields_preserved"] == {
            "p1_service_points_won": 1,
        }
        assert e.enrich(m) == "cached"  # no repeated provider attempt
    finally:
        e.close()


@pytest.mark.parametrize("existing,ace", [
    ({"p1_service_points_won": 0.600001}, 7),
    ({"p1_aces": 7}, 7.00000000005),
    ({"p1_aces": 8}, 7),
    ({"p1_aces": True}, 1),  # bool must not equal provider count 1
    ({"p1_service_points_won": float("inf")}, 7),
])
def test_material_rate_or_any_count_conflict_quarantines_entire_response(
        match_factory, tmp_path, existing, ace):
    m = match_with_verified_id(match_factory, existing)
    before = dict(m.stats)
    provider = Provider(ace_value=ace)
    e = StatisticsEnricher(provider, tmp_path / "conflict.sqlite",
                           targeted=True, break_points_focus=True)
    try:
        assert e.enrich(m) == "conflict"
        assert m.stats == before
        assert "p1_break_point_return_win" not in m.stats
        assert m.provider_payload["_tbt_statistics"]["status"] == "conflict"
        assert e.conflict_diagnostics()["rejected_responses"] == 1
        assert provider.calls == 1
    finally:
        e.close()


def test_exact_numeric_equivalence_never_coerces_existing_number_type(
        match_factory, tmp_path):
    m = match_with_verified_id(
        match_factory, {"p1_aces": 7, "p1_service_points_won": 0.6})
    before = dict(m.stats)
    e = StatisticsEnricher(Provider(), tmp_path / "types.sqlite",
                           targeted=True, break_points_focus=True)
    try:
        assert e.enrich(m) == "enriched"
        assert m.stats["p1_aces"] is before["p1_aces"]
        assert m.stats["p1_service_points_won"] == before["p1_service_points_won"]
        assert m.stats["p1_break_point_serve_win"] == 3 / 5
    finally:
        e.close()
