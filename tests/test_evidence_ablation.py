"""Synthetic only: no real data claims, no CDB writes and no model activation."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pandas as pd
import pytest

from tbt.models.evidence_lab import HistoricalEvidence, DIL_FEATURE_NAMES
from tbt.models.evidence_ablation import run_dil_research_ablation, canonical_dil_evidence_digest
from tbt.schemas import MatchRecord


BASE = ("elo_probability", "serve_quality_diff", "return_quality_diff", "tour_atp")
FIRST = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)


def synthetic(n=760):
    matches, evidence, rows = [], [], []
    for idx in range(n):
        tour = "ATP" if idx % 2 == 0 else "WTA"
        a, b = f"{tour}-A", f"{tour}-B"
        day = FIRST + timedelta(days=idx // 2)
        mid = f"m-{idx}"
        winner = a if idx % 3 else b
        match = MatchRecord(match_id=mid, tour=tour, scheduled_at=day,
                            player1_id=a, player2_id=b,
                            player1_name=a, player2_name=b, winner_id=winner,
                            surface="hard" if idx % 6 else "clay",
                            tournament_level="main", status="completed")
        matches.append(match)
        rows.append({
            "match_id": mid, "scheduled_at": day, "tour": tour.lower(),
            "surface": match.surface, "competition": "main",
            "target": int(winner == a),
            "elo_probability": 0.48 + (idx % 7) * 0.007,
            "serve_quality_diff": (idx % 9 - 4) / 100,
            "return_quality_diff": (idx % 11 - 5) / 100,
            "tour_atp": float(tour == "ATP"),
        })
        for player, own_won in ((a, winner == a), (b, winner == b)):
            evidence.append(HistoricalEvidence(
                canonical_match_id=mid, tour=tour, player_id=player,
                surface=match.surface, started_at=day,
                completed_at=day + timedelta(hours=2),
                available_at=day + timedelta(hours=3),
                expected_recorded_at=day - timedelta(hours=2),
                won=own_won, expected_win=.5,
                service_points=90, first_in=60,
                first_won=40 + (idx % 8), second_won=16,
                opponent_service_points=100,
                opponent_first_won=35, opponent_second_won=23,
                bp_saved=4, bp_faced=6,
                opponent_bp_saved=5, opponent_bp_faced=9,
                reviewed_cdb_link=True,
            ))
    return pd.DataFrame(rows), matches, evidence


def run(frame, matches, evidence, **overrides):
    settings = dict(original_721_feature_names=BASE,
                    canonical_source_sha256="a" * 64,
                    dil_sidecar_sha256=canonical_dil_evidence_digest(evidence),
                    min_paired_by_tour=20, estimator_max_iter=8)
    settings.update(overrides)
    return run_dil_research_ablation(frame, matches, evidence, **settings)


def test_paired_candidate_fit_uses_real_model_contract_and_only_frozen_history():
    frame, matches, evidence = synthetic()
    original = frame.copy(deep=True)
    report = run(frame, matches, evidence)
    assert frame.equals(original)
    assert report["state"] == "OFFLINE_RESEARCH_DESCRIPTIVE_NOT_PROMOTION"
    assert report["fit"]["baseline_721"]["feature_count"] == len(BASE)
    assert report["fit"]["new_dil"]["feature_count"] == len(BASE) + len(DIL_FEATURE_NAMES)
    assert report["overall"]["n"] > 0
    assert report["segments"]["tour"]["atp"]["n"] > 0
    assert report["segments"]["tour"]["wta"]["n"] > 0
    assert report["segments"]["competition"]["main"]["n"] == report["overall"]["n"]
    assert all(report["partition_coverage"][partition][tour]["paired_serve_return"] >= 20
               for partition in ("train", "calibration", "descriptive_test")
               for tour in ("atp", "wta"))
    assert report["models_promoted"] == report["cdb_writes"] == report["provider_requests"] == 0
    assert report["can_promote"] is False


def test_ablation_refuses_fake_baseline_schema_and_unverified_provenance():
    frame, matches, evidence = synthetic(4)
    with pytest.raises(ValueError, match="original 7.2.1 feature schema"):
        run(frame, matches, evidence, original_721_feature_names=["elo_probability"])
    with pytest.raises(ValueError, match="SHA256"):
        run(frame, matches, evidence, canonical_source_sha256="no")
    with pytest.raises(ValueError, match="DIL source row digest mismatch"):
        run(frame, matches, evidence, dil_sidecar_sha256="b" * 64)
    with pytest.raises(ValueError, match="link"):
        run(frame, matches, [replace(evidence[0], reviewed_cdb_link=False), *evidence[1:]])


def test_ablation_fails_closed_without_paired_history_and_without_stable_cohort():
    frame, matches, evidence = synthetic(4)
    late = [replace(x, available_at=FIRST + timedelta(days=3000)) for x in evidence]
    with pytest.raises(ValueError, match="No paired PIT"):
        run(frame, matches, late, min_paired_by_tour=1)
    # Independent row/source equality is required even when the sole sidecar row is valid.
    with pytest.raises(ValueError, match="exact verified match cohort"):
        run(frame.iloc[:-1], matches, evidence)
