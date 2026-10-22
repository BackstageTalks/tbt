"""Promote a protected frozen training *candidate* to shadow only after offline gates.

Runs solely inside the existing protected training workflow. This never
writes the serving champion, never calls providers and never mutates CDB.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from guarded_candidate_backup import validate_certificate
from pipeline import _promotion_metric_gate
from activate_shadow_candidate import activate, REPO, CANDIDATE


def _current_candidate_digest():
    cmd = subprocess.run(["gh", "api", f"repos/{REPO}/releases/tags/{CANDIDATE}"],
                         capture_output=True, text=True)
    if cmd.returncode:
        raise RuntimeError("Current shadow candidate release inaccessible")
    data = json.loads(cmd.stdout)
    records = [a for a in data.get("assets", []) if a.get("name") == "model.joblib"]
    if len(records) != 1:
        raise RuntimeError("Ambiguous current candidate model asset")
    digest = str(records[0].get("digest") or "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise RuntimeError("Current shadow digest is not independently verifiable")
    return digest.split(":", 1)[1]


def offline_gate(report, certificate) -> tuple[bool, list[str]]:
    reasons = []
    if not certificate or certificate.get("status") != "VERIFIED_FULL_INPUTS_AND_ISOLATED_RESTORE":
        reasons.append("unverified_full_input_backup")
    if certificate.get("champion_restore", {}).get("status") != "PASS":
        reasons.append("unverified_champion_restore")
    if (report.get("immutable_training_backup") or {}).get("candidate_tag") != certificate.get("candidate_tag"):
        reasons.append("candidate_training_source_mismatch")
    if (report.get("promotion_decision") or {}).get("promotion_requested") is not False:
        reasons.append("production_promotion_was_requested")
    if not (report.get("evaluation_governance") or {}).get("holdout_fingerprint"):
        reasons.append("missing_untouched_holdout")
    gate_ok, failures = _promotion_metric_gate(report)
    if not gate_ok:
        reasons.extend(failures)
    # Positive accuracy gain is required for the poor-serving-champion case:
    # a lower log-loss alone does not qualify as clearly stronger shadow.
    challenger = (report.get("holdout") or {}).get("accuracy")
    champion = (report.get("production_holdout") or {}).get("accuracy")
    if not isinstance(challenger, (int, float)) or not isinstance(champion, (int, float)):
        reasons.append("missing_champion_accuracy")
    elif challenger <= champion + 0.01:
        reasons.append("insufficient_accuracy_gain_for_automatic_shadow")
    return not reasons, reasons


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "BackstageTalks/tbt"):
        raise RuntimeError("Not a protected GitHub candidate training job")
    cert = validate_certificate()
    report = json.loads((ROOT / ".cache/tbt/model/training_report.json").read_text())
    accepted, reasons = offline_gate(report, cert)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not accepted:
        message = "Shadow NOT activated: " + ", ".join(reasons)
        print(message, flush=True)
        if summary:
            with open(summary, "a", encoding="utf-8") as out:
                out.write("\n### Model Factory · shadow blocked\n" + message + "\n")
        return
    # Immutable source release and current shadow SHA are both verified again
    # inside activate(), which also checks unchanged production and rollback.
    result = activate(cert["candidate_tag"], _current_candidate_digest())
    if result.get("production_mutated") is not False or result.get("remote_readback") != "VERIFIED":
        raise RuntimeError("Independent shadow activation readback failed")
    print(json.dumps(result, sort_keys=True), flush=True)
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("\n### Model Factory · candidate shadow active\n")
            out.write(f"Candidate: \`{result['candidate_version']}\` · source: \`{result['source_tag']}\`\n")
            out.write("Production champion unchanged; prospective shadow evidence is still required.\n")


if __name__ == "__main__":
    main()
