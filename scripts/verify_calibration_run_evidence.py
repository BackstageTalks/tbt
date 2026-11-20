"""Read-only exact-run calibration gate. Historical holdout is not prospective TOP proof.

This never fits, selects, promotes or contacts bookmaker/tennis providers.
An exit code of zero means evidence was analyzed, NOT model approval.
"""
import argparse
import json
import math
from pathlib import Path
import re
import zipfile

FILES = {"report": "model/training_report.json",
         "certificate": "training-backup/verified-certificate.json",
         "leakage": "production/leakage_audit_report.json"}


def _metrics(row, label):
    if not isinstance(row, dict) or type(row.get("n")) is not int or row["n"] < 1:
        raise ValueError("Missing/invalid " + label + " scores")
    result = {"n": row["n"]}
    for key in ("accuracy", "brier_score", "log_loss", "ece_10"):
        v = row.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("Invalid " + label + " " + key)
        result[key] = float(v)
    if not (0 <= result["accuracy"] <= 1 and 0 <= result["ece_10"] <= 1
            and 0 <= result["brier_score"] <= 1 and result["log_loss"] >= 0):
        raise ValueError("Out-of-range " + label + " scores")
    return result



def _quality_cohort_evidence(report, *, holdout_n, known_weekly_ranks, champion, candidate):
    """Verify already-saved same-fixture feature-availability cohorts; do not fit.

    Historical count depth is NOT an independent measurement of paired
    serve/return or point-in-time ranking availability. This audit cannot
    authorize promotion or retrospectively select publication thresholds.
    """
    evidence = report.get("pit_evidence_holdout") or {}
    if (evidence.get("status") != "PAIRED_UNSEEN_HOLDOUT"
            or evidence.get("holdout_only") is not True
            or evidence.get("never_select_on_holdout") is not True):
        raise ValueError("Missing frozen, paired, read-only feature evidence")
    cohorts = evidence.get("cohorts")
    keys = {f"stats_{stats}_rank_{rank}" for stats in (0, 1) for rank in (0, 1)}
    if not isinstance(cohorts, dict) or set(cohorts) != keys:
        raise ValueError("Feature evidence cohorts must form the four PIT groups")

    verified = {}
    sums = {"candidate": {"accuracy": 0., "brier_score": 0.},
            "champion": {"accuracy": 0., "brier_score": 0.}}
    count = 0
    for key in sorted(keys):
        group = cohorts[key]
        size = group.get("n") if isinstance(group, dict) else None
        if type(size) is not int or not 0 <= size <= holdout_n:
            raise ValueError("Invalid feature evidence cohort count")
        count += size
        scores = {}
        for side in ("candidate", "champion"):
            raw = group.get(side)
            if size == 0:
                if raw is not None:
                    raise ValueError("Empty feature evidence cohort has scores")
                continue
            if not isinstance(raw, dict) or raw.get("n") != size:
                raise ValueError("Unpaired feature evidence scores")
            vals = {}
            for name in ("accuracy", "brier_score", "mean_confidence"):
                value = raw.get(name)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not 0 <= value <= 1):
                    raise ValueError("Invalid feature evidence " + name)
                vals[name] = float(value)
            for name in ("accuracy", "brier_score"):
                sums[side][name] += size * vals[name]
            scores[side] = vals
        verified[key] = {
            "n": size,
            "candidate_confidence_minus_accuracy": (
                scores["candidate"]["mean_confidence"] - scores["candidate"]["accuracy"]
                if size else None),
            "champion_confidence_minus_accuracy": (
                scores["champion"]["mean_confidence"] - scores["champion"]["accuracy"]
                if size else None),
            "same_fixture_brier_delta": (
                scores["candidate"]["brier_score"] - scores["champion"]["brier_score"]
                if size else None),
            "small_sample": size < 100,
        }
    if count != holdout_n:
        raise ValueError("Feature evidence does not partition the fixed holdout")
    rank_known = cohorts["stats_0_rank_1"]["n"] + cohorts["stats_1_rank_1"]["n"]
    if rank_known != known_weekly_ranks:
        raise ValueError("Feature evidence disagrees with verified weekly rank coverage")
    for side, overall in (("candidate", candidate), ("champion", champion)):
        for metric in ("accuracy", "brier_score"):
            if not math.isclose(sums[side][metric] / count, overall[metric],
                                abs_tol=1e-6, rel_tol=0):
                raise ValueError("Feature evidence does not reconcile with holdout")

    supported = [item for item in verified.values() if not item["small_sample"]]
    return {
        "status": "VERIFIED_DESCRIPTIVE_ONLY",
        "total": count,
        "paired_serve_return_available": (
            cohorts["stats_1_rank_0"]["n"] + cohorts["stats_1_rank_1"]["n"]),
        "paired_weekly_ranks_available": rank_known,
        "paired_both_available": cohorts["stats_1_rank_1"]["n"],
        "groups": verified,
        "supported_group_brier_nonregression": (
            bool(supported) and all(item["same_fixture_brier_delta"] <= 1e-12
                                    for item in supported)),
        "training_or_publication_authorized": False,
    }


def analyze(report, cert, leakage, *, expected_commit):
    """Invalid identity/integrity => error. Insufficient accuracy => BLOCKED."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("Exact 40-character source commit required")
    if cert.get("application_sha") != expected_commit:
        raise ValueError("Protected run code differs from expected commit")
    run, attempt = str(cert.get("run_id") or ""), str(cert.get("attempt") or "")
    manifest = str(cert.get("remote_manifest_sha256") or "")
    if (not run.isdigit() or not attempt.isdigit()
            or not re.fullmatch(r"[0-9a-f]{64}", manifest)
            or not re.fullmatch(r"[0-9a-f]{64}", str(cert.get("champion_sha256") or ""))):
        raise ValueError("Missing protected run/digest evidence")
    if (cert.get("status") != "VERIFIED_FULL_INPUTS_AND_ISOLATED_RESTORE"
            or type(cert.get("all_assets_remotely_verified")) is not int
            or cert["all_assets_remotely_verified"] < 1
            or cert.get("canonical_mutated") is not False
            or cert.get("production_mutated") is not False
            or cert.get("provider_requests") != 0):
        raise ValueError("Input backup/immutable state not verified")
    restore = cert.get("champion_restore") or {}
    if (restore.get("status") != "PASS"
            or restore.get("restored_version") != cert.get("champion_version")
            or restore.get("max_prediction_difference") != 0.0):
        raise ValueError("Champion isolated restoration not verified")
    cache = leakage.get("verified_feature_cache") or {}
    if (leakage.get("status") != "pass" or leakage.get("failed_checks") != []
            or not leakage.get("checks")
            or not all(v is True for v in leakage["checks"].values())
            or (str(cache.get("run_id")), str(cache.get("attempt")),
                cache.get("application_sha"), cache.get("backup_manifest_sha256"))
            != (run, attempt, expected_commit, manifest)
            or type(cache.get("rows")) is not int or cache["rows"] != leakage.get("rows")):
        raise ValueError("Point-in-time/leakage verification does not match run")
    decision = report.get("promotion_decision") or {}
    if (decision.get("production_version") != cert.get("champion_version")
            or not decision.get("candidate_version")
            or decision.get("holdout_fingerprint") !=
               (report.get("evaluation_governance") or {}).get("holdout_fingerprint")
            or not decision.get("holdout_fingerprint")
            or decision.get("promotion_requested") is not False):
        raise ValueError("Champion/candidate/holdout identity mismatch")
    champion = _metrics(report.get("production_holdout"), "champion")
    candidate = _metrics(report.get("holdout"), "candidate")
    if (champion["n"] != candidate["n"]
            or candidate["n"] != (report.get("data") or {}).get("holdout")):
        raise ValueError("Not a same-holdout candidate/champion comparison")
    group = ((report.get("context_calibration_holdout") or {}).get("groups") or {}).get("all") or {}
    if group.get("n") != candidate["n"]:
        raise ValueError("Context-disabled ablation is not paired")
    parent, context = group.get("parent") or {}, group.get("candidate") or {}
    if any(not math.isclose(float(context.get(t, float("nan"))), candidate[s],
                                rel_tol=0, abs_tol=1e-10)
           for s, t in (("brier_score", "brier"), ("log_loss", "log_loss"))):
        raise ValueError("Context-enabled ablation does not equal saved candidate")
    rank_groups = ((report.get("rank_reliability_holdout") or {}).get("groups") or {})
    known = (rank_groups.get("weekly_rank_pair_known") or {}).get("n")
    missing = (rank_groups.get("weekly_rank_pair_missing") or {}).get("n")
    if (type(known) is not int or type(missing) is not int
            or known < 0 or missing < 0 or known + missing != candidate["n"]):
        raise ValueError("Verified rank groups do not partition fixed holdout")
    quality = _quality_cohort_evidence(
        report, holdout_n=candidate["n"], known_weekly_ranks=known,
        champion=champion, candidate=candidate)
    delta = {key: candidate[key] - champion[key] for key in
             ("accuracy", "brier_score", "log_loss", "ece_10")}
    wta = ((report.get("subgroups") or {}).get("tour") or {}).get("wta") or {}
    old_wta = ((report.get("production_subgroups") or {}).get("tour") or {}).get("wta") or {}
    wta_ece_ok = (isinstance(wta.get("ece_10"), (int, float))
                  and isinstance(old_wta.get("ece_10"), (int, float))
                  and math.isfinite(wta["ece_10"])
                  and wta["ece_10"] <= old_wta["ece_10"])
    top = report.get("top_market_validation") or {}
    gates = {
        "proper_score_improvement": delta["brier_score"] < 0 and delta["log_loss"] < 0,
        "ece_nonregression": delta["ece_10"] <= 0,
        "wta_ece_nonregression": bool(wta_ece_ok),
        "verified_weekly_rank_holdout": (
            (report.get("rank_alignment") or {}).get("status") == "PIT_WEEKLY_ALIGNED"
            and known > 0),
        "real_top_issuance_validated": (
            top.get("status") == "PASS" and top.get("promotion_ready_for_top") is True),
        "new_prospective_top_validated": False,
    }
    reasons = [name for name, ok in gates.items() if not ok]
    return {
        "status": "BLOCKED_PRODUCTION_PROMOTION",
        "protected_run_id": run,
        "application_sha": expected_commit,
        "champion_version": cert["champion_version"],
        "champion_sha256": cert["champion_sha256"],
        "candidate_version": decision["candidate_version"],
        "backup_manifest_sha256": manifest,
        "holdout": {"n": candidate["n"], "champion": champion,
                    "candidate": candidate, "delta_candidate_minus_champion": delta,
                    "development_influenced_not_prospective": True},
        "context_ablation": {
            "no_context": parent, "context_enabled": context,
            "selected_maps": (report.get("evaluation_model") or {}).get(
                "context_calibration_methods") or []},
        "feature_quality_holdout": quality,
        "verified_weekly_rank_holdout": {"known_both": known, "missing": missing,
                                         "coverage": known / candidate["n"]},
        "gates": gates, "blockers": reasons,
        "provider_requests": 0, "model_or_cdb_modified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    with zipfile.ZipFile(args.artifact) as z:
        if set(z.namelist()) != set(FILES.values()) or len(z.namelist()) != len(FILES):
            raise ValueError("Expected exactly the three protected evidence reports")
        entries = {k: json.loads(z.read(v)) for k, v in FILES.items()}
    result = analyze(entries["report"], entries["certificate"], entries["leakage"],
                     expected_commit=args.expected_commit)
    body = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
    print(body, end="")
    # Success means only that an independently inspectable BLOCKED report exists.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
