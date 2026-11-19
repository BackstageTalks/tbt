"""Read-only, issuance-timestamped champion vs challenger comparison.

Never fits a model, replays an outcome into pre-match features, calls a tennis
provider, or changes a model/CDB/public prediction release. Settlement reflects
the last published private shadow ledger, which may lag latest CDB outcomes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
import random
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore
from tbt.models.artifact import load_model
from tbt.models.metrics import evaluate_probabilities
from tbt.services.shadow_evaluation import build_shadow_report
from tbt.services.shadow_calibration_research import research_comparison


def _datetime(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Shadow date lacks timezone")
    return d.astimezone(timezone.utc)


def validate_cohort(rows, production_version, challenger_version):
    """Refuse duplicate, after-start, invalid or outcome-mismatched paired rows."""
    seen = set()
    cohort = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid private shadow ledger row")
        if (row.get("production_model_version") != production_version or
                row.get("challenger_model_version") != challenger_version):
            continue
        match_id = str(row.get("match_id") or "")
        if not match_id or match_id in seen:
            raise ValueError("Duplicate/blank match identity in model pair")
        seen.add(match_id)
        captured = _datetime(row.get("captured_at"))
        scheduled = _datetime(row.get("scheduled_at"))
        if captured >= scheduled:
            raise ValueError("Shadow prediction issued after scheduled match start")
        for name in ("production_player1_probability", "challenger_player1_probability"):
            value = float(row[name])
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError("Invalid pre-match model probability")
        if row.get("status") == "settled":
            target = row.get("target_player1_win")
            if type(target) is not int or target not in (0, 1):
                raise ValueError("Invalid settled match outcome")
            for prefix in ("production", "challenger"):
                observed = row.get(prefix + "_correct")
                expected = (float(row[prefix + "_player1_probability"]) >= .5) == bool(target)
                if type(observed) is not bool or observed != expected:
                    raise ValueError("Stored outcome/model prediction disagreement")
        elif row.get("status") not in ("pending", "void", "excluded"):
            raise ValueError("Unrecognized shadow outcome state")
        cohort.append(row)
    return cohort



def cohort_forensics(rows, production_version, challenger_version):
    """Independent, aggregate-only ledger accounting; no outcome-driven selection.

    The raw shadow ledger does not necessarily include level, data depth,
    form, or issuer-price snapshots. Never infer those fields from later data.
    """
    from collections import Counter

    cohort = validate_cohort(rows, production_version, challenger_version)
    status = Counter()
    capture_days, scheduled_days, settled_days = Counter(), Counter(), Counter()
    by_tour, by_surface = {}, {}
    excluded_reasons, void_reasons = Counter(), Counter()
    tournament_counts, tournament_labels_by_tour = Counter(), {}
    agreement = Counter()
    agree_by_tour, agree_by_surface = {}, {}
    lead_buckets = Counter()
    ids, events = set(), set()
    duplicated_event_ids = 0
    missing_player_ids = 0
    inconsistent_recorded_winner = 0
    missing_pricing = 0
    feature_fields = Counter()
    first, last = None, None
    first_start, last_start = None, None
    for row in cohort:
        match = str(row["match_id"])
        ids.add(match)
        event = str(row.get("event_id") or "")
        if event:
            duplicated_event_ids += int(event in events)
            events.add(event)
        state = str(row["status"])
        status[state] += 1
        capture = _datetime(row["captured_at"])
        scheduled = _datetime(row["scheduled_at"])
        first = min(first, capture) if first else capture
        last = max(last, capture) if last else capture
        first_start = min(first_start, scheduled) if first_start else scheduled
        last_start = max(last_start, scheduled) if last_start else scheduled
        capture_days[capture.date().isoformat()] += 1
        scheduled_days[scheduled.date().isoformat()] += 1
        if state == "settled":
            settled_days[scheduled.date().isoformat()] += 1
        lead = (scheduled - capture).total_seconds()
        bucket = ("under_15m" if lead < 900 else "15m_to_1h" if lead < 3600
                  else "1h_to_24h" if lead < 86400 else "over_24h")
        lead_buckets[bucket] += 1
        tour = str(row.get("tour") or "unknown").upper()
        surface = str(row.get("surface") or "unknown").lower()
        for key, label, out in (("tour", tour, by_tour),
                                ("surface", surface, by_surface)):
            if label not in out:
                out[label] = Counter()
            out[label][state] += 1
        tournament = str(row.get("tournament") or "").strip()
        if tournament:
            tournament_counts[(tour, tournament)] += 1
            tournament_labels_by_tour.setdefault(tour, set()).add(tournament)
        if state == "excluded":
            excluded_reasons[str(row.get("excluded_reason") or "UNSPECIFIED")] += 1
        if state == "void":
            void_reasons[str(row.get("excluded_reason") or "UNSPECIFIED")] += 1
        p1, p2 = str(row.get("player1_id") or ""), str(row.get("player2_id") or "")
        if not p1 or not p2 or p1 == p2:
            missing_player_ids += 1
        if state == "settled":
            target = int(row["target_player1_win"])
            known_winner = str(row.get("result_winner_id") or "")
            if known_winner and p1 and p2 and (
                    known_winner != (p1 if target else p2)):
                inconsistent_recorded_winner += 1
            old = float(row["production_player1_probability"]) >= .5
            new = float(row["challenger_player1_probability"]) >= .5
            truth = bool(target)
            group = ("both_correct" if old == truth and new == truth
                     else "both_wrong" if old != truth and new != truth
                     else "candidate_only_correct" if new == truth
                     else "champion_only_correct")
            agreement[group] += 1
            agree_by_tour.setdefault(tour, Counter())[group] += 1
            agree_by_surface.setdefault(surface, Counter())[group] += 1
        # No retrospective odds backfill: this documents the unsupported scope.
        if not isinstance(row.get("two_way_market"), dict):
            missing_pricing += 1
        for field in ("data_depth", "opponent_adjusted_form_diff",
                      "surface_elo_diff", "competition_level", "weekly_rank_diff",
                      "recent_form", "layoff_advantage"):
            if row.get(field) is not None:
                feature_fields[field] += 1
    counts = dict(status)
    expected = {"settled", "pending", "void", "excluded"}
    if set(counts) - expected or sum(counts.values()) != len(cohort):
        raise ValueError("Shadow ledger states do not reconcile")
    if inconsistent_recorded_winner:
        raise ValueError("Canonical winner ID disagrees with settled pair")
    if missing_player_ids:
        raise ValueError("Incomplete paired player identities")
    # Reconcile every provider-event duplicate with its original immutable
    # first-captured row, without modifying either status or selecting a
    # "better" outcome. An unexplained pointer is a review item, not a win.
    by_match = {str(row["match_id"]): row for row in cohort}
    duplicate_links = Counter()
    duplicate_primary_status = Counter()
    itf_label_by_tour = {}
    itf_label_by_tour_status = {}
    for row in cohort:
        tour = str(row.get("tour") or "unknown").upper()
        status_label = str(row.get("status") or "")
        label = str(row.get("tournament") or "").strip()
        group = "explicit_itf" if label.upper().startswith("ITF ") else "not_explicit_itf"
        itf_label_by_tour.setdefault(tour, Counter())[group] += 1
        itf_label_by_tour_status.setdefault(tour, {}).setdefault(group, Counter())[status_label] += 1
        if status_label != "excluded" or row.get("excluded_reason") != "duplicate_provider_event_snapshot":
            continue
        first = by_match.get(str(row.get("primary_match_id") or ""))
        if first is None or first is row:
            duplicate_links["missing_primary"] += 1
            continue
        if not row.get("event_id") or str(first.get("event_id")) != str(row["event_id"]):
            duplicate_links["provider_event_mismatch"] += 1
            continue
        if (str(first.get("tour") or "").upper() != tour
                or first.get("production_model_version") != row.get("production_model_version")
                or first.get("challenger_model_version") != row.get("challenger_model_version")
                or {str(first.get("player1_id")), str(first.get("player2_id"))}
                != {str(row.get("player1_id")), str(row.get("player2_id"))}):
            duplicate_links["player_or_model_identity_mismatch"] += 1
            continue
        if _datetime(first.get("captured_at")) > _datetime(row.get("captured_at")):
            duplicate_links["primary_after_duplicate"] += 1
            continue
        duplicate_links["verified_original_event_pair"] += 1
        if _datetime(first.get("scheduled_at")) != _datetime(row.get("scheduled_at")):
            duplicate_links["schedule_changed"] += 1
        duplicate_primary_status[str(first.get("status") or "unknown")] += 1
    total_duplicate = sum(
        row.get("excluded_reason") == "duplicate_provider_event_snapshot"
        for row in cohort)
    verified = duplicate_links.get("verified_original_event_pair", 0)
    duplicate_status = ("VERIFIED_FIRST_EVENT_SNAPSHOT_LINKS"
                        if verified == total_duplicate else "REVIEW_MISSING_OR_CONFLICTING_DUPLICATE_LINKS")
    return {
        "status": "READ_ONLY_LEDGER_FORENSICS",
        "raw_ledger_rows": len(rows),
        "active_pair_captured": len(cohort),
        "other_model_pairs": len(rows) - len(cohort),
        "unique_match_ids": len(ids),
        "unique_nonempty_event_ids": len(events),
        "repeated_nonempty_event_ids": duplicated_event_ids,
        "statuses": {k: counts.get(k, 0) for k in sorted(expected)},
        "capture_first_utc": first.isoformat() if first else None,
        "capture_last_utc": last.isoformat() if last else None,
        "scheduled_first_utc": first_start.isoformat() if first_start else None,
        "scheduled_last_utc": last_start.isoformat() if last_start else None,
        "capture_utc_days": dict(sorted(capture_days.items())),
        "scheduled_utc_days": dict(sorted(scheduled_days.items())),
        "settled_utc_days": dict(sorted(settled_days.items())),
        "prestart_lead_buckets": dict(sorted(lead_buckets.items())),
        "by_tour_status": {k: dict(sorted(v.items())) for k, v in sorted(by_tour.items())},
        "by_surface_status": {k: dict(sorted(v.items())) for k, v in sorted(by_surface.items())},
        "void_reason_counts": dict(sorted(void_reasons.items())),
        "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
        "excluded_duplicate_link_status": duplicate_status,
        "excluded_duplicate_link_counts": dict(sorted(duplicate_links.items())),
        "duplicate_primary_status_counts": dict(sorted(duplicate_primary_status.items())),
        "explicit_itf_label_by_tour": {
            k: dict(sorted(v.items())) for k, v in sorted(itf_label_by_tour.items())},
        "explicit_itf_label_by_tour_status": {
            k: {g: dict(sorted(c.items())) for g, c in sorted(v.items())}
            for k, v in sorted(itf_label_by_tour_status.items())},
        "paired_winner_outcomes": dict(sorted(agreement.items())),
        "changed_winner_by_tour": {k: {
            "candidate_only_correct": v.get("candidate_only_correct", 0),
            "champion_only_correct": v.get("champion_only_correct", 0)}
            for k, v in sorted(agree_by_tour.items())},
        "changed_winner_by_surface": {k: {
            "candidate_only_correct": v.get("candidate_only_correct", 0),
            "champion_only_correct": v.get("champion_only_correct", 0)}
            for k, v in sorted(agree_by_surface.items())},
        "tournament_label_count_by_tour": {
            k: len(v) for k, v in sorted(tournament_labels_by_tour.items())},
        "most_frequent_tournament_labels": [
            {"tour": k[0], "tournament": k[1], "captured": n}
            for k, n in sorted(tournament_counts.items(),
                               key=lambda kv: (-kv[1], kv[0]))[:15]],
        "rows_missing_embedded_two_way_quote": missing_pricing,
        "available_context_field_counts": dict(sorted(feature_fields.items())),
        "competition_level_status": (
            "NOT_IN_SHADOW_LEDGER" if not feature_fields.get("competition_level")
            else "PARTIALLY_PRESENT_USE_VERIFIED_SOURCE"),
        "selection_scope": (
            "Same-match model winner probabilities only; own TOP choice and "
            "priced >=1.50 selection require separate issued quote evidence."),
        "no_provider_requests": True,
        "no_model_fit_or_deploy": True,
    }


def _metrics(rows):
    if not rows:
        return {}
    y = [int(r["target_player1_win"]) for r in rows]
    def single(key):
        result = evaluate_probabilities(y, (r[key] for r in rows))
        return {name: (round(value, 8) if isinstance(value, (int, float))
                        and math.isfinite(value) else None)
                for name, value in result.items()
                if name in ("n", "accuracy", "brier_score", "log_loss", "ece_10", "roc_auc")}
    return {"champion": single("production_player1_probability"),
            "challenger": single("challenger_player1_probability")}



def _paired_confidence(rows, *, samples=1200):
    """Paired bootstrap on the original unchanged fixture pairs, never a new fit.

    Confidence intervals are descriptive because fixtures within the four-day
    shadow can be correlated; they are not independent release authorization.
    """
    if not rows:
        return {"n": 0, "status": "INSUFFICIENT"}
    differences = {"accuracy_pp": [], "log_loss": [], "brier_score": []}
    challenger_only = champion_only = 0
    for row in rows:
        y = int(row["target_player1_win"])
        p = float(row["production_player1_probability"])
        q = float(row["challenger_player1_probability"])
        a = int((p >= 0.5) == bool(y))
        b = int((q >= 0.5) == bool(y))
        challenger_only += int(b == 1 and a == 0)
        champion_only += int(a == 1 and b == 0)
        differences["accuracy_pp"].append(100.0 * (b - a))
        differences["brier_score"].append((y - q) ** 2 - (y - p) ** 2)
        differences["log_loss"].append(
            -math.log(q if y else 1.0 - q) + math.log(p if y else 1.0 - p)
        )
    n = len(rows)
    rng = random.Random(711)  # repeatable descriptive uncertainty
    intervals = {}
    for metric, values in differences.items():
        draws = []
        for _ in range(samples):
            draws.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
        draws.sort()
        intervals[metric] = {
            "delta": round(sum(values) / n, 6),
            "ci95_paired_fixture_bootstrap": [
                round(draws[int(samples * .025)], 6),
                round(draws[min(samples-1, int(samples * .975))], 6),
            ],
        }
    discordant = challenger_only + champion_only
    p_exact = (
        min(1.0, 2.0 * sum(math.comb(discordant, k) for k in range(min(challenger_only, champion_only) + 1))
            / (2 ** discordant))
        if discordant else 1.0
    )
    return {
        "n": n,
        "settled_utc_days": len({_datetime(r["scheduled_at"]).date().isoformat() for r in rows}),
        "challenger_only_correct": challenger_only,
        "champion_only_correct": champion_only,
        "mcnemar_exact_two_sided_p": round(p_exact, 6),
        "paired_deltas": intervals,
        "inference_limit": "Fixture bootstrap assumes independence; few days and correlated tournaments widen real uncertainty.",
    }


def _segment_release_screen(cohort, overall_gate, segments):
    """Bounded-segment shadow review; independent Elo/rollback gate remains separate."""
    reasons = []
    if not overall_gate.get("ready_for_promotion_review", False):
        reasons.append("aggregate_shadow_gate_not_met")
    segment_results = {}
    for tour in ("ATP", "WTA"):
        group = (segments.get("tour") or {}).get(tour, {})
        champion, candidate = group.get("champion") or {}, group.get("challenger") or {}
        n = int(candidate.get("n") or 0)
        failures = []
        if n < 50 or n != int(champion.get("n") or 0):
            failures.append("sample_below_50_or_unpaired")
        else:
            for metric in ("accuracy", "log_loss", "brier_score", "ece_10"):
                old, new = champion.get(metric), candidate.get(metric)
                if (old is None or new is None or not math.isfinite(float(old))
                        or not math.isfinite(float(new))):
                    failures.append(metric + "_missing_or_nonfinite")
            if not failures:
                if candidate["accuracy"] < champion["accuracy"] - 0.05:
                    failures.append("accuracy_material_regression")
                if candidate["log_loss"] > champion["log_loss"] + 0.03:
                    failures.append("log_loss_material_regression")
                if candidate["brier_score"] > champion["brier_score"] + 0.015:
                    failures.append("brier_material_regression")
        segment_results[tour] = {"n": n, "strict_gate_pass": not failures, "reasons": failures}
        reasons.extend(tour.lower() + "_" + reason for reason in failures)
    return {
        "status": "SHADOW_SEGMENTS_PASS" if not reasons else "SHADOW_SEGMENT_REGRESSIONS",
        "reasons": reasons, "segments": segment_results,
        "official_promotion": "NOT_EVALUATED_REQUIRES_CANONICAL_ELO_GATE_AND_OPERATOR_APPROVAL",
        "production_change_authorized": False,
        "recommendation": "REVIEW_ONLY_NO_PRODUCTION_SWITCH" if reasons else "RUN_SEPARATE_PROMOTION_GOVERNANCE",
    }

def summarize(rows, production_version, challenger_version, source_ts=None):
    if production_version == challenger_version:
        raise ValueError("Challenger is identical to champion")
    cohort = validate_cohort(rows, production_version, challenger_version)
    summary = build_shadow_report(
        cohort, production_model_version=production_version,
        challenger_model_version=challenger_version,
    )
    settled = [r for r in cohort if r["status"] == "settled"]
    segments = {}
    for field in ("tour", "surface"):
        segments[field] = {}
        for label in sorted({str(r.get(field) or "unknown") for r in settled}):
            segment = [r for r in settled if str(r.get(field) or "unknown") == label]
            if len(segment) >= 30:
                segments[field][label] = _metrics(segment)
    last_capture = max((str(r["captured_at"]) for r in cohort), default=None)
    return {
        "schema": 1,
        "status": ("EVALUATED" if len(settled) >= 200 and summary["cohort"]["settled_utc_days"] >= 3
                   else "INSUFFICIENT_PAIRED_SAMPLE"),
        "source_shadow_last_generated_at": source_ts,
        "last_pre_match_capture": last_capture,
        "production_model_version": production_version,
        "challenger_model_version": challenger_version,
        "cohort": summary["cohort"],
        "ledger_forensics": cohort_forensics(rows, production_version, challenger_version),
        "overall": _metrics(settled),
        "paired": summary["paired"],
        "calibration_research": research_comparison(cohort, production_version, challenger_version),
        "gate": summary["gate"],
        "segments": segments,
        "paired_uncertainty": {
            label: _paired_confidence(
                [r for r in settled if label == "all" or
                 str(r.get("tour") or "").upper() == label]
            )
            for label in ("all", "ATP", "WTA")
        },
        "release_screen": _segment_release_screen(cohort, summary["gate"], segments),
        "roi_yield_status": "NOT_EVALUABLE_WITHOUT_VERIFIED_PREMATCH_ODDS",
        "limits": [
            "No retraining or modification of model artifacts, CDB or public predictions.",
            "Settlements reflect the last private shadow ledger update, not independently refreshed outcomes.",
            "Comparison uses identical originally issued matches; sample size and age must be considered.",
            "The shadow test does not establish incremental benefit of today's CDB imports.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    parser.add_argument("--out", type=Path, default=ROOT / ".cache/tbt/model-shadow-audit/report.json")
    args = parser.parse_args()
    if not os.environ.get("GH_TOKEN"):
        parser.error("Private release read token unavailable")
    root = ROOT / ".cache/tbt/model-shadow-audit"
    production = ReleaseStore(args.data_repository, "tbt-model-production-v1", root / "production")
    candidate = ReleaseStore(args.data_repository, "tbt-model-candidate-v1", root / "candidate")
    shadow = ReleaseStore(args.data_repository, "tbt-model-shadow-v1", root / "shadow")
    production.download(required_names=("model.joblib", "training_report.json"),
                        require_bundle_manifest=True)
    candidate.download(required_names=("model.joblib",), require_bundle_manifest=True)
    shadow.download(required_names=("shadow_ledger.json", "shadow_report.json"),
                    require_bundle_manifest=True)
    champion = load_model(str(production.directory / "model.joblib"))
    challenger = load_model(str(candidate.directory / "model.joblib"))
    if not champion.fitted or not challenger.fitted:
        raise ValueError("Unfitted model artifact")
    ledger = json.loads((shadow.directory / "shadow_ledger.json").read_text())
    previous = json.loads((shadow.directory / "shadow_report.json").read_text())
    if not isinstance(ledger, list) or not isinstance(previous, dict):
        raise ValueError("Malformed shadow release")
    result = summarize(
        ledger, str(champion.version), str(challenger.version),
        source_ts=previous.get("generated_at_utc"),
    )
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["sources"] = {
        "champion_sha256": sha256((production.directory / "model.joblib").read_bytes()).hexdigest(),
        "challenger_sha256": sha256((candidate.directory / "model.joblib").read_bytes()).hexdigest(),
        "shadow_ledger_sha256": sha256((shadow.directory / "shadow_ledger.json").read_bytes()).hexdigest(),
        "release_tags": ["tbt-model-production-v1", "tbt-model-candidate-v1", "tbt-model-shadow-v1"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False, sort_keys=True) + "\n")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
