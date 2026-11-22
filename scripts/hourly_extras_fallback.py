"""Choose a same-writer extras continuation only after independently verified stats.

The hourly importer owns the canonical CDB lock. This helper NEVER calls a
provider, CDB, or budget endpoint. Both the primary and fallback importer
retain the shared CAS ledger, 500 provider reserve, 6/s throttle, and UTC
cutoff. No fallback is allowed for unverified/ordinary statistics runs.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


REASONS = frozenset({
    "cross_tour_paid_statistics_unavailable",
    "verified_prior_zero_gain_cross_tour_recheck",
    "cross_tour_paid_zero_cdb_yield_plateau",
})


def plan(download, readback, evidence, *, original_limit: int, run_id: str,
         cutoff: datetime, now: datetime) -> dict:
    """Return an auditable plan, never an unaccounted new quota allowance."""
    result = {
        "schema": 1, "status": "SKIPPED", "reason": "not_eligible",
        "allowed": False, "max_requests": 0, "original_limit": original_limit,
        "run_id": str(run_id),
    }

    def skip(reason):
        return {**result, "reason": reason}

    if not all(isinstance(v, dict) for v in (download, readback, evidence)):
        return skip("missing_or_invalid_verified_evidence")
    if (type(original_limit) is not int or not 1 <= original_limit <= 5000
            or not str(run_id).isdigit()):
        return skip("invalid_hourly_run_allowance")
    if (now.tzinfo is None or cutoff.tzinfo is None
            or now.utcoffset() is None or cutoff.utcoffset() is None):
        return skip("untrusted_provider_time")
    now = now.astimezone(timezone.utc)
    cutoff = cutoff.astimezone(timezone.utc)
    next_reset = now.replace(hour=17, minute=9, second=0, microsecond=0)
    if now >= next_reset:
        next_reset += timedelta(days=1)
    if cutoff != next_reset - timedelta(minutes=2):
        return skip("cutoff_not_current_provider_day")
    # The second native importer bootstraps local history from private CDB.
    # Refuse starts too near rollover, never borrow the next provider day.
    if cutoff - now > timedelta(hours=4):
        return skip("reserve_early_provider_day_for_primary_statistics")
    if cutoff - now <= timedelta(minutes=12):
        return skip("insufficient_time_before_utc_cutoff")
    if (readback.get("status") not in ("VERIFIED", "VERIFIED_NO_NEW_FIELDS")
            or evidence.get("status") not in ("VERIFIED_CDB_GAIN", "VERIFIED_NO_GAIN")
            or evidence.get("run_id") != str(run_id)):
        return skip("statistics_remote_readback_not_verified")
    try:
        paid = download["requests_including_retries"]
        verified_paid = evidence["requests_including_retries"]
        persisted = readback["persisted_new_statistic_values"]
        verified_persisted = evidence["persisted_new_statistic_values"]
    except KeyError:
        return skip("missing_paid_or_persisted_metrics")
    if (type(paid) is not int or type(verified_paid) is not int
            or type(persisted) is not int or type(verified_persisted) is not int
            or not 0 <= paid <= original_limit or paid != verified_paid
            or persisted < 0 or persisted != verified_persisted):
        return skip("inconsistent_verified_metrics")
    if paid == original_limit:
        return skip("original_run_allowance_exhausted")
    # An exhausted, independently verified statistics queue is also a valid
    # reason to use the *remaining* allowance for provider-native extras.
    # Without this route, tiny hourly queues (or entirely cooled-down queues)
    # leave thousands of governed requests idle even when extras have backlog.
    # Do not infer exhaustion from a missing report or from a partial scan.
    # A small (1..7) fully scanned queue with exact paid all-empty responses
    # and same-run independent CDB read-back is just as exhausted as >=8.
    # Avoid a statistical threshold here: full exhaustion is hard evidence.
    queue_size = download.get("statistics_candidate_rows")
    adaptive = download.get("statistics_adaptive_priority")
    unavailable = download.get("statistics_unavailable_reasons")
    if (type(queue_size) is int and isinstance(adaptive, dict)
            and isinstance(unavailable, dict)
            and all(type(adaptive.get(key)) is int for key in
                    ("candidate_rows", "selected_rows", "remaining_rows"))
            and adaptive["candidate_rows"] == queue_size
            and adaptive["selected_rows"] == queue_size
            and adaptive["remaining_rows"] == 0
            and persisted == 0):
        empty_count = unavailable.get("empty_whole_match_statistics", 0)
        no_candidates = (queue_size == 0 and paid == 0
                         and type(empty_count) is int and empty_count == 0)
        all_unavailable = (queue_size >= 1 and paid >= queue_size
                           and type(empty_count) is int
                           and empty_count == queue_size)
        if no_candidates or all_unavailable:
            remaining = original_limit - paid
            if remaining < 1:
                return skip("original_run_allowance_exhausted")
            return {
                **result, "status": "ELIGIBLE",
                "reason": ("verified_statistics_queue_empty" if no_candidates
                           else "verified_statistics_queue_exhausted_unavailable"),
                "allowed": True, "max_requests": remaining,
                "statistics_paid_requests": paid,
                "cutoff_utc": cutoff.isoformat(),
                "evidence": "same_run_remote_CDB_readback_and_exhausted_statistics_queue",
            }

    circuit = download.get("statistics_availability_circuit")
    if not isinstance(circuit, dict) or circuit.get("tripped") is not True:
        return skip("statistics_route_not_stopped_by_availability_circuit")
    trigger = circuit.get("trigger")
    if not isinstance(trigger, dict):
        return skip("unverified_availability_trigger")
    recent = trigger.get("recent_paid_matches")
    unavailable = trigger.get("recent_unavailable_matches")
    sampled = trigger.get("sampled_cohorts")
    tours = trigger.get("sampled_tours")
    attempts = trigger.get("recent_paid_attempts")
    reason = trigger.get("reason")
    zero_gain_plateau = reason == "cross_tour_paid_zero_cdb_yield_plateau"
    expected_min = (240 if zero_gain_plateau else
                    24 if reason == "verified_prior_zero_gain_cross_tour_recheck"
                    else 120)
    if (reason not in REASONS
            or trigger.get("scope") != "current_high_yield_statistics_run_only"
            or any(type(v) is not int for v in
                   (recent, unavailable, sampled, tours, attempts))
            or recent < expected_min or attempts < expected_min
            or not 0 <= unavailable <= recent
            or (not zero_gain_plateau and unavailable * 100 < 95 * recent)
            or (zero_gain_plateau and (attempts > paid or recent > paid))
            or trigger.get("recent_new_canonical_fields") != 0
            or sampled < 3 or tours < 2):
        return skip("insufficient_cross_tour_paid_unavailability_evidence")
    remaining = original_limit - paid
    if remaining < 1:
        return skip("original_run_allowance_exhausted")
    return {
        **result, "status": "ELIGIBLE",
        "reason": ("verified_statistics_zero_cdb_yield" if zero_gain_plateau
                   else "verified_statistics_unavailable"),
        "allowed": True, "max_requests": remaining,
        "statistics_paid_requests": paid,
        "cutoff_utc": cutoff.isoformat(),
        "evidence": ("same_run_remote_CDB_readback_and_paid_zero_gain_plateau"
                     if zero_gain_plateau else
                     "same_run_remote_CDB_readback_and_paid_cross_tour_circuit"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--max-requests", required=True, type=int)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--stop-at", required=True)
    ap.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    args = ap.parse_args()
    root = Path(args.history_dir)

    def read(filename):
        return json.loads((root / filename).read_text(encoding="utf-8"))

    try:
        cutoff = datetime.fromisoformat(args.stop_at.replace("Z", "+00:00"))
        result = plan(
            read("download_report.json"), read("statistics_readback.json"),
            read("adaptive_cdb_evidence.json"), original_limit=args.max_requests,
            run_id=args.run_id, cutoff=cutoff, now=datetime.now(timezone.utc),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # A corrupt/missing optional fallback plan must never spend API calls
        # or undo already independently verified primary CDB gains.
        result = {
            "schema": 1, "status": "SKIPPED", "allowed": False,
            "max_requests": 0, "reason": "fallback_plan_unavailable",
            "error_type": type(exc).__name__,
        }
    root.mkdir(parents=True, exist_ok=True)
    (root / "hourly_extras_fallback_plan.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as out:
            out.write("allowed=" + str(result["allowed"]).lower() + "\n")
            out.write("max_requests=" + str(result["max_requests"]) + "\n")
    print(json.dumps({"hourly_extras_fallback": result}, sort_keys=True),
          flush=True)


if __name__ == "__main__":
    main()
