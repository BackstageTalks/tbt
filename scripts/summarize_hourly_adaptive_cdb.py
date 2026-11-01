"""Fail-closed, offline evidence summary for scheduled adaptive CDB API batches.

Only consumes locally written download report and independent remote read-back.
No additional provider calls, CDB writes, secrets, or model-performance claims.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def build(download: dict, readback: dict, *, run_id: str = "") -> dict:
    if not isinstance(download, dict) or not isinstance(readback, dict):
        raise ValueError("Missing structured collector/readback evidence")
    adaptive = download.get("statistics_adaptive_priority")
    value = download.get("statistics_data_value")
    if not isinstance(adaptive, dict) or not isinstance(value, dict):
        raise ValueError("Scheduled statistics run lacks adaptive or CDB gain evidence")
    if adaptive.get("policy") != "bounded_online_observed_cdb_yield_v1":
        raise ValueError("Unknown adaptive selection implementation")
    status = readback.get("status")
    if status not in ("VERIFIED", "VERIFIED_NO_NEW_FIELDS"):
        raise ValueError("CDB read-back not verified")
    requests = int(download.get("requests_including_retries", -1))
    observed = int(adaptive.get("observed_paid_requests", -1))
    new_fields = int(value.get("new_statistic_values", -1))
    persisted = int(readback.get("persisted_new_statistic_values", -1))
    if requests < 0 or requests != observed:
        raise ValueError("Paid API usage differs from adaptive feedback")
    if new_fields < 0 or persisted != new_fields:
        raise ValueError("Collector gains differ from persisted CDB values")
    if status == "VERIFIED_NO_NEW_FIELDS" and persisted:
        raise ValueError("Contradictory zero-gain read-back")
    selected = int(adaptive.get("selected_rows", -1))
    baseline = int(adaptive.get("baseline_choices", -1))
    adapted = int(adaptive.get("adaptive_choices", -1))
    if min(selected, baseline, adapted) < 0 or selected != baseline + adapted:
        raise ValueError("Adaptive choice accounting inconsistent")
    if adapted > 0 and adaptive.get("online_adaptation_used") is not True:
        raise ValueError("Adaptive choices not acknowledged")
    if baseline < (selected + 3) // 4:
        raise ValueError("Original exploration fell below its guaranteed 25% share")
    cohorts = adaptive.get("cohorts")
    if not isinstance(cohorts, dict):
        raise ValueError("Missing actual cohort evidence")
    per_cohort = []
    for name, item in sorted(cohorts.items()):
        spent = int(item.get("paid_requests", -1))
        fresh = int(item.get("new_statistic_values", -1))
        ready = int(item.get("new_quality_ready_rows", -1))
        if min(spent, fresh, ready) < 0:
            raise ValueError("Invalid cohort values")
        per_cohort.append({
            "cohort": name,
            "api_requests": spent,
            "new_fields": fresh,
            "full_serve_return_rows": ready,
            "new_fields_per_1000_api": round(1000 * fresh / spent, 1) if spent else None,
            "baseline_choices": int(item.get("baseline_choices", 0)),
            "adaptive_choices": int(item.get("adaptive_choices", 0)),
        })
    if sum(x["api_requests"] for x in per_cohort) != observed:
        raise ValueError("Cohort spend does not reconcile with provider usage")
    if sum(x["new_fields"] for x in per_cohort) != int(value.get("api_new_statistic_values", -1)):
        raise ValueError("Cohort paid gains do not reconcile")
    return {
        "schema": 1,
        "parser_version": download.get("statistics_schema_version"),
        "status": "VERIFIED_CDB_GAIN" if persisted else "VERIFIED_NO_GAIN",
        "run_id": str(run_id),
        "reported_at_utc": datetime.now(timezone.utc).isoformat(),
        "requests_including_retries": requests,
        "persisted_new_statistic_values": persisted,
        "persisted_per_set_matches": int(readback.get("persisted_new_per_set_matches", 0)),
        "new_ace_df_values": int(value.get("new_ace_df_values", 0)),
        "new_full_serve_return_rows": int(value.get("new_quality_ready_rows", 0)),
        "persisted_new_fields_per_1000_requests": (
            round(1000 * persisted / requests, 1) if requests else None
        ),
        "adaptive_choices": adapted,
        "baseline_choices": baseline,
        "adaptive_choice_share": round(adapted / selected, 4) if selected else 0,
        "adaptive_used": bool(adapted),
        "cohorts": per_cohort,
        "evidence": "Remote exact-value and SHA256 CDB read-back confirmed",
        "model_accuracy_verified": False,
    }


def markdown(report: dict) -> str:
    lines = [
        "## BlinQ adaptive hourly CDB – independent evidence",
        f"- Run: \u0060{report['run_id']}\u0060",
        f"- Read-back: **{report['status']}**",
        f"- Paid RapidAPI requests (with retries): **{report['requests_including_retries']:,}**",
        f"- Actual persisted new fields: **{report['persisted_new_statistic_values']:,}**",
        f"- New full serve+return rows: **{report['new_full_serve_return_rows']:,}**",
        f"- New Aces / DF fields: **{report['new_ace_df_values']:,}**",
        f"- Persisted per-set match records: **{report['persisted_per_set_matches']:,}**",
        f"- Persisted values per 1,000 calls: **{report['persisted_new_fields_per_1000_requests']}**",
        f"- Adaptive / baseline selections: **{report['adaptive_choices']:,} / {report['baseline_choices']:,}**",
        "",
        "| ATP/WTA / year / type | Calls | New fields | Quality rows | Fields/1k | Adaptive picks |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(report["cohorts"], key=lambda r: (-r["new_fields"], r["cohort"])):
        lines.append(
            f"| {row['cohort']} | {row['api_requests']} | {row['new_fields']} "
            f"| {row['full_serve_return_rows']} | {row['new_fields_per_1000_api']} "
            f"| {row['adaptive_choices']} |")
    lines += [
        "",
        "Values are independently verified CDB increments, not candidate counts.",
        "Model prediction accuracy is not established by this run.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--github-step-summary", default="")
    args = ap.parse_args()
    root = Path(args.history_dir)
    download = json.loads((root / "download_report.json").read_text(encoding="utf-8"))
    readback = json.loads((root / "statistics_readback.json").read_text(encoding="utf-8"))
    result = build(download, readback, run_id=args.run_id)
    (root / "adaptive_cdb_evidence.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rendered = markdown(result)
    (root / "adaptive_cdb_evidence.md").write_text(rendered, encoding="utf-8")
    if args.github_step_summary:
        with Path(args.github_step_summary).open("a", encoding="utf-8") as out:
            out.write(rendered)
    print(json.dumps({k: v for k, v in result.items() if k != "cohorts"}, sort_keys=True))


if __name__ == "__main__":
    main()
