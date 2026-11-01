"""Prevent avoidable RapidAPI requests in the current-board ace/DF job."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from enrich_ace_history import _needs_ace_df_request
from tbt.services.statistics_enrichment import StatisticsEnricher, STATISTICS_SCHEMA_VERSION


def _match(stats=None):
    return SimpleNamespace(
        player1_id="A", player2_id="B", stats=stats or {},
    )


def test_only_missing_target_player_market_justifies_lookup():
    match = _match({"p1_aces": 4, "p2_double_faults": 3})
    coverage = {"A": {"aces": 1, "double_faults": 0},
                "B": {"aces": 8, "double_faults": 8}}

    # Aces already present in this match; A's DF is a useful gap.
    assert _needs_ace_df_request(match, {"A"}, coverage, 5)
    assert not _needs_ace_df_request(match, {"B"}, coverage, 5)
    assert not _needs_ace_df_request(match, set(), coverage, 5)

    # During the run A reaches DF target, while other players may still lag.
    coverage["A"]["double_faults"] = 5
    assert not _needs_ace_df_request(match, {"A"}, coverage, 5)


def test_cached_existing_counts_do_not_spend_even_with_low_sample_coverage():
    match = _match({"p1_aces": 0, "p1_double_faults": 0})
    coverage = {"A": {"aces": 2, "double_faults": 2}}
    assert not _needs_ace_df_request(match, {"A"}, coverage, 18)


def test_second_current_player_still_gets_missing_market_when_first_is_ready():
    match = _match({"p1_aces": 3, "p1_double_faults": 2, "p2_aces": 3})
    coverage = {"A": {"aces": 18, "double_faults": 18},
                "B": {"aces": 1, "double_faults": 1}}
    assert _needs_ace_df_request(match, {"A", "B"}, coverage, 18)
    match.stats["p2_double_faults"] = 1
    assert not _needs_ace_df_request(match, {"A", "B"}, coverage, 18)


def test_ace_job_targeted_retry_uses_due_statistics_marker_without_extra_detail(
    match_factory, tmp_path,
):
    class Provider:
        def __init__(self):
            self.calls = []

        def _get(self, path, **kwargs):
            self.calls.append(path)
            assert path == "/api/tennis/event/123/statistics"
            return {"statistics": [{"period": "ALL", "groups": [{
                "statisticsItems": [
                    {"name": "Aces", "home": "5", "away": "3"},
                    {"name": "Double faults", "home": "2", "away": "1"},
                ],
            }]}]}

    match = match_factory("ace-sample", "A", "B", "A")
    match.stats = {"p1_service_points_won": 0.6}
    match.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "home": "A", "away": "B", "status": "finished",
        },
        "_tbt_statistics": {
            "schema": STATISTICS_SCHEMA_VERSION, "event_id": "123",
            "status": "available",
            "fetched_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
        },
    }
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path / "ace.sqlite", targeted=True)
    try:
        assert enricher.enrich(match) == "enriched"
        assert provider.calls == ["/api/tennis/event/123/statistics"]
        assert match.stats["p1_aces"] == 5
        assert match.stats["p2_double_faults"] == 1
        assert enricher.enrich(match) == "cached"
        assert len(provider.calls) == 1
    finally:
        enricher.close()
