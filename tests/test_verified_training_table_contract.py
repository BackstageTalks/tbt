"""Synthetic regressions for the prepublication table gate."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from scripts.verify_training_table_contract import validate, validate_weather_identity


def fixtures(n=1200):
    frame = pd.DataFrame({
        "match_id": [f"atp-{i}" for i in range(n)] + [f"wta-{i}" for i in range(n)],
        "scheduled_at": pd.to_datetime(
            ["2024-06-01T12:00:00Z"] * (n * 2), utc=True
        ),
        "tour": ["atp"] * n + ["wta"] * n,
        "atp_hist_known_both": [1.0] * n + [0.0] * n,
        "wta_hist_known_both": [0.0] * n + [1.0] * n,
        "pre_match_weather_known": [1.0] * (n * 2),
    })
    report = {
        "rows": len(frame),
        "date_range": {
            "from": "2024-06-01 12:00:00+00:00",
            "to": "2024-06-01 12:00:00+00:00",
        },
        "atp_rank_history": {"known_both_rate": 0.5},
        "wta_rank_history": {"known_both_rate": 0.5},
        "pre_match_forecast_weather": {
            "known_rows": len(frame), "lead_hours": 24,
            "post_hoc_weather_used": False,
        },
        "verified_rank_inputs": {
            "status": "verified", "provider_requests": 0,
            "sources": {
                "sackmann-atp-rankings.tar.gz": {"sha256": "a" * 64},
                "sackmann-wta-rankings.tar.gz": {"sha256": "b" * 64},
            },
        },
    }
    leakage = {"status": "pass", "rows": len(frame), "failed_checks": []}
    weather = {"status": "verified", "fixed_forecast_lead_hours": 24,
               "provider_requests": 0}
    return frame, report, leakage, weather


def test_good_per_tour_modern_coverage_passes():
    frame, report, leakage, weather = fixtures()
    result = validate(frame, report, leakage, weather_evidence=weather)
    assert result["status"] == "verified"
    assert result["segments"]["atp_2024+"]["known_both_rate"] == 1


def test_missing_ranks_are_rejected_even_when_columns_exist():
    frame, report, leakage, weather = fixtures()
    frame.loc[frame.tour == "atp", "atp_hist_known_both"] = 0
    report["atp_rank_history"]["known_both_rate"] = 0
    with pytest.raises(ValueError, match="coverage regression"):
        validate(frame, report, leakage, weather_evidence=weather)


def test_report_disagreement_is_rejected():
    frame, report, leakage, weather = fixtures()
    report["wta_rank_history"]["known_both_rate"] = 0.1
    with pytest.raises(ValueError, match="report differs"):
        validate(frame, report, leakage, weather_evidence=weather)


def test_weather_drop_and_source_integrity_are_rejected():
    frame, report, leakage, weather = fixtures()
    frame["pre_match_weather_known"] = 0
    report["pre_match_forecast_weather"]["known_rows"] = 0
    with pytest.raises(ValueError, match="weather coverage regression"):
        validate(frame, report, leakage, weather_evidence=weather)
    frame, report, leakage, weather = fixtures()
    weather["status"] = "unverified"
    with pytest.raises(ValueError, match="not verified"):
        validate(frame, report, leakage, weather_evidence=weather)


def test_dupe_identity_and_leakage_fail_closed():
    frame, report, leakage, weather = fixtures()
    frame.loc[1, "match_id"] = frame.loc[0, "match_id"]
    with pytest.raises(ValueError, match="Duplicate"):
        validate(frame, report, leakage, weather_evidence=weather)
    frame, report, leakage, weather = fixtures()
    leakage["failed_checks"] = ["time_order_violation"]
    with pytest.raises(ValueError, match="failed"):
        validate(frame, report, leakage, weather_evidence=weather)


def test_rank_source_provenance_is_required():
    frame, report, leakage, weather = fixtures()
    report["verified_rank_inputs"] = None
    with pytest.raises(ValueError, match="verified private ranking"):
        validate(frame, report, leakage, weather_evidence=weather)


def test_weather_identity_uses_exact_prematch_utc_fixture(tmp_path):
    frame, _, _, _ = fixtures()
    weather = frame[["match_id", "scheduled_at"]].copy()
    weather["source"] = "open-meteo-previous-runs"
    weather["forecast_reference"] = "previous_day1"
    weather["forecast_lead_hours"] = 24
    out = tmp_path / "verified_weather.csv"
    weather.to_csv(out, index=False)
    assert validate_weather_identity(frame, out) == len(frame)
    weather.loc[0, "scheduled_at"] = "2025-06-01T12:00:00Z"
    weather.to_csv(out, index=False)
    with pytest.raises(ValueError, match="match_id/date"):
        validate_weather_identity(frame, out)
    weather.loc[0, "scheduled_at"] = "2024-06-01T12:00:00Z"
    weather.loc[0, "source"] = "untrusted-posthoc"
    weather.to_csv(out, index=False)
    with pytest.raises(ValueError, match="verified Previous Runs"):
        validate_weather_identity(frame, out)
