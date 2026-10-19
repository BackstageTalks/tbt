"""Offline regression checks for exact CDB and adaptive action reporting."""
import json
from pathlib import Path

import pytest

from summarize_hourly_adaptive_cdb import build, markdown, main


def evidence():
    download = {
        "requests_including_retries": 100,
        "statistics_data_value": {
            "new_statistic_values": 30, "api_new_statistic_values": 30,
            "new_quality_ready_rows": 2, "new_ace_df_values": 8,
        },
        "statistics_adaptive_priority": {
            "policy": "bounded_online_observed_cdb_yield_v1",
            "observed_paid_requests": 100, "selected_rows": 100,
            "min_paid_requests": 80,
            "baseline_choices": 50, "adaptive_choices": 50,
            "online_adaptation_used": True,
            "cohorts": {
                "atp:2025:serve_return": {
                    "paid_requests": 60, "new_statistic_values": 30,
                    "new_quality_ready_rows": 2,
                    "baseline_choices": 30, "adaptive_choices": 30,
                },
                "wta:2026:serve_return": {
                    "paid_requests": 40, "new_statistic_values": 0,
                    "new_quality_ready_rows": 0,
                    "baseline_choices": 20, "adaptive_choices": 20,
                },
            },
        },
    }
    verified = {
        "status": "VERIFIED", "persisted_new_statistic_values": 30,
        "persisted_new_per_set_matches": 5,
    }
    return download, verified


def test_confirmed_evidence_exposes_persisted_values_and_priority_by_cohort():
    download, verified = evidence()
    result = build(download, verified, run_id="123")
    assert result["status"] == "VERIFIED_CDB_GAIN"
    assert result["persisted_new_statistic_values"] == 30
    assert result["requests_including_retries"] == 100
    assert result["persisted_new_fields_per_1000_requests"] == 300
    assert result["adaptive_choices"] == 50
    assert result["adaptive_used"] is True
    assert result["model_accuracy_verified"] is False
    assert "| atp:2025:serve_return | 60 | 30 | 2 | 500.0 | 30 |" in markdown(result)


def test_missing_independent_confirmation_is_not_a_success():
    download, verified = evidence()
    verified["status"] = "FAILED"
    with pytest.raises(ValueError, match="read-back"):
        build(download, verified)
    verified["status"] = "VERIFIED"
    verified["persisted_new_statistic_values"] = 29
    with pytest.raises(ValueError, match="persisted"):
        build(download, verified)


def test_missing_adaptive_or_inconsistent_requests_are_rejected():
    download, verified = evidence()
    del download["statistics_adaptive_priority"]
    with pytest.raises(ValueError, match="lacks adaptive"):
        build(download, verified)
    download, verified = evidence()
    download["statistics_adaptive_priority"]["observed_paid_requests"] = 99
    with pytest.raises(ValueError, match="usage"):
        build(download, verified)


def test_cohort_sum_and_choice_accounting_must_match():
    download, verified = evidence()
    download["statistics_adaptive_priority"]["cohorts"]["atp:2025:serve_return"]["paid_requests"] = 59
    with pytest.raises(ValueError, match="spend"):
        build(download, verified)
    download, verified = evidence()
    download["statistics_adaptive_priority"]["adaptive_choices"] = 49
    with pytest.raises(ValueError, match="choice"):
        build(download, verified)


def test_valid_no_gain_is_not_misreported_as_import_success():
    download, verified = evidence()
    download["statistics_data_value"]["new_statistic_values"] = 0
    download["statistics_data_value"]["api_new_statistic_values"] = 0
    for cohort in download["statistics_adaptive_priority"]["cohorts"].values():
        cohort["new_statistic_values"] = 0
    verified["status"] = "VERIFIED_NO_NEW_FIELDS"
    verified["persisted_new_statistic_values"] = 0
    report = build(download, verified)
    assert report["status"] == "VERIFIED_NO_GAIN"
    assert report["persisted_new_statistic_values"] == 0


def test_render_writes_valid_json_and_markdown_without_provider_calls(tmp_path, monkeypatch):
    download, verified = evidence()
    (tmp_path / "download_report.json").write_text(json.dumps(download))
    (tmp_path / "statistics_readback.json").write_text(json.dumps(verified))
    summary = tmp_path / "github-step-summary.md"
    monkeypatch.setattr("sys.argv", [
        "summarize_hourly_adaptive_cdb.py", "--history-dir", str(tmp_path),
        "--run-id", "456", "--github-step-summary", str(summary),
    ])
    main()
    result = json.loads((tmp_path / "adaptive_cdb_evidence.json").read_text())
    assert result["run_id"] == "456"
    assert result["status"] == "VERIFIED_CDB_GAIN"
    assert "remote" not in summary.read_text().lower()  # no unverified external fetch
    assert "independent evidence" in summary.read_text()
