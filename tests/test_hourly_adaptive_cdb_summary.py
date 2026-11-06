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


def test_summary_schema2_explicitly_separates_paid_and_cache_gain():
    download, verified = evidence()
    download["statistics_data_value"]["new_statistic_values"] = 35
    verified["persisted_new_statistic_values"] = 35
    result = build(download, verified)
    assert result["schema"] == 2
    assert result["persisted_new_statistic_values"] == 35
    assert result["paid_new_statistic_values"] == 30
    assert result["non_paid_new_statistic_values"] == 5
    assert result["paid_new_fields_per_1000_requests"] == 300
    assert result["persisted_new_fields_per_1000_requests"] == 300
    assert "cache/local processing: **5**" in markdown(result)


def test_cutoff_before_first_paid_call_with_missing_counter_keys():
    download, verified = evidence()
    download["requests_including_retries"] = 0
    download["statistics_data_value"] = {"policy": "zero-request cutoff"}
    download["statistics_adaptive_priority"].update({
        "observed_paid_requests": 0,
        "selected_rows": 1,
        "baseline_choices": 1,
        "adaptive_choices": 0,
        "online_adaptation_used": False,
        "cohorts": {"atp:2026:serve_return": {
            "paid_requests": 0, "new_statistic_values": 0,
            "new_quality_ready_rows": 0,
            "baseline_choices": 1, "adaptive_choices": 0,
        }},
    })
    verified.update({
        "status": "VERIFIED_NO_NEW_FIELDS",
        "persisted_new_statistic_values": 0,
        "persisted_new_per_set_matches": 0,
    })
    result = build(download, verified, run_id="cutoff")
    assert result["status"] == "VERIFIED_NO_GAIN"
    assert result["requests_including_retries"] == 0
    assert result["persisted_new_statistic_values"] == 0
    assert result["paid_new_statistic_values"] == 0
    assert result["paid_new_fields_per_1000_requests"] is None


def test_missing_counters_cannot_hide_independently_persisted_gain():
    download, verified = evidence()
    download["statistics_data_value"] = {}
    with pytest.raises(ValueError, match="persisted"):
        build(download, verified)


def test_hourly_closeout_starts_early_and_keeps_authoritative_limits():
    workflow = (Path(__file__).resolve().parents[1]
                / ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    assert "16: 12000, 17: 13500, 18: 13500" in workflow
    assert "limit = 14500 if final_topup else caps[stage_hour]" in workflow
    assert "if now >= cutoff - timedelta(minutes=15):" in workflow
    assert "min(5000, limit-spent" in workflow
    assert 'budget.get("global_limit") != 14500' in workflow
    assert 'budget.get("reserved_provider_headroom") != 500' in workflow
    assert "wait_for_writer(check_writers, retry_deadline)" in workflow
    assert '"mode": "statistics"' in workflow


def test_malformed_paid_gain_is_not_misreported_from_readback():
    download, verified = evidence()
    download["statistics_data_value"]["api_new_statistic_values"] = 29
    with pytest.raises(ValueError, match="Cohort paid gains"):
        build(download, verified)
    download, verified = evidence()
    download["statistics_data_value"]["api_new_statistic_values"] = 31
    with pytest.raises(ValueError, match="Paid and non-paid"):
        # 31 alleged paid values but only 30 persisted.
        build(download, verified)
