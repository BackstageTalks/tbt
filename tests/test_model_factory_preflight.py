"""Contract tests for read-only Model Factory ATP/WTA preparation."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import model_factory_preflight as m


def fake_match(tour, stats=None, rank1=42, rank2=81):
    return SimpleNamespace(
        tour=tour, scheduled_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        player1_rank=rank1, player2_rank=rank2, stats=stats or {},
    )


def test_preflight_counts_tour_and_existing_stats_without_imputation():
    rows = [
        fake_match("atp", {"p1_service_points_total": 80, "p1_return_points_won": 23,
                           "p1_break_points_won_count": 4}),
        fake_match("wta", {"p1_serve_points": 90}, rank2=None),
        fake_match("wta"),
    ]
    with patch.object(m, "audit_history", return_value=(rows, {"rejected": 0})):
        with patch.object(m, "Counter", wraps=m.Counter):
            original_min = m.inspect.__globals__["audit_history"]
            # use a full synthetic cohort, not a production escape hatch
            many = rows * 200000
            result = m.inspect(many, app_sha="a" * 40, source_manifest_digest="b" * 64)
    assert result["status"] == "READ_ONLY_PREFLIGHT_COMPLETE_NOT_FROZEN"
    assert result["tours"]["atp"]["eligible_matches"] == 200000
    assert result["tours"]["wta"]["eligible_matches"] == 400000
    assert result["tours"]["atp"]["coverage_counts"]["break_points"] == 200000
    assert result["tours"]["wta"]["coverage_counts"]["rank_pair"] == 0
    assert result["provider_requests"] == 0
    assert result["cdb_mutations"] == 0
    assert result["production_mutations"] == 0


def test_small_or_rejected_source_fails_closed():
    with patch.object(m, "audit_history", return_value=([], {"rejected": 1})):
        try:
            m.inspect([fake_match("atp")], app_sha="a" * 40,
                      source_manifest_digest="b" * 64)
        except ValueError as e:
            assert "unexpectedly small" in str(e)
        else:
            raise AssertionError("Preflight accepted an invalid cohort")
