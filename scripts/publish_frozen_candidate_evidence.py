"""Publish an independently backed-up candidate's *offline* holdout comparison.

Never confuses an untouched holdout with a forward shadow cohort. Does not
promote, train, modify canonical data, or overwrite model release artifacts.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from _bootstrap import ROOT
from guarded_candidate_backup import validate_certificate

DATA_REPO="BackstageTalks/tbt-data"
PRIVATE_PATH="audit/model-frozen-candidate-latest.json"


def run(*args, input=None):
    result=subprocess.run(args, input=input, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def score(block):
    from tbt.services.model_calibration_status import _metric_row
    if not isinstance(block,dict):
        raise ValueError("Model comparison metrics missing")
    metric=_metric_row(block)
    for key in ("accuracy", "log_loss", "brier_score", "ece_10"):
        if key not in metric:
            raise ValueError(f"Required holdout metric missing: {key}")
    n=block.get("n")
    if type(n) is not int or n<200:
        raise ValueError("Holdout comparison has insufficient sample size")
    return {"n":n, **metric}


def make_evidence(cert, report, candidate_binary):
    old=score(report.get("production_holdout"))
    new=score(report.get("holdout"))
    if old["n"]!=new["n"]:
        raise ValueError("Candidate and champion were not scored on same holdout")
    decision=report.get("promotion_decision") or {}
    if decision.get("promotion_requested") is not False:
        raise ValueError("A nonpromoting candidate is required")
    if decision.get("production_version")!=cert["champion_version"]:
        raise ValueError("Evaluated champion version differs from immutable backup")
    version=decision.get("candidate_version")
    if not isinstance(version,str) or not version.strip():
        raise ValueError("No fitted candidate model version in training report")
    gov=report.get("evaluation_governance") or {}
    if not gov.get("holdout_fingerprint"):
        raise ValueError("No untouched holdout fingerprint")
    assert cert["candidate_tag"].startswith("blinq-candidate-frozen-")
    raw=candidate_binary.read_bytes()
    if not raw:
        raise ValueError("Candidate binary absent")
    sub=report.get("subgroups") or {}
    return {
        "schema":1,"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "status":"EVALUATED_NOT_DEPLOYED","evaluation_type":"untouched_offline_holdout",
        "run_id":cert["run_id"],"run_attempt":cert["attempt"],
        "application_sha":cert["application_sha"],
        "backup_tag":cert["backup_tag"],"backup_manifest_sha256":cert["remote_manifest_sha256"],
        "candidate_release_tag":cert["candidate_tag"],
        "candidate_sha256":hashlib.sha256(raw).hexdigest(),
        "champion_version":cert["champion_version"],
        "champion_sha256":cert["champion_sha256"],
        "candidate_version":version,
        "comparison":{"sample_size":new["n"],"champion":old,"candidate":new,
                      "subgroups":{k:v for k,v in sub.items() if k=="tour" and isinstance(v,dict)}},
        "holdout_fingerprint":gov["holdout_fingerprint"],
        "holdout_period":(report.get("periods") or {}).get("holdout"),
        "gate":{"eligible":bool(decision.get("eligible",False)),
                "reasons":[str(x)[:90] for x in decision.get("reasons",[])[:12]]},
        "backup_readback_verified":True,"champion_restore_verified":True,
        "promotion_requested":False,"model_promoted":False,
        "provider_requests":0,"canonical_mutated":False,
        "source_note":"Comparison is offline holdout, not an issued pre-match shadow cohort.",
    }


def persist_verified(payload):
    raw=(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
    existing=subprocess.run(["gh","api",f"repos/{DATA_REPO}/contents/{PRIVATE_PATH}"],
                            text=True,capture_output=True)
    body={"message":f"evidence(model): new nonpromoted candidate evaluation run {payload['run_id']}",
          "content":base64.b64encode(raw).decode()}
    if existing.returncode==0:
        body["sha"]=json.loads(existing.stdout)["sha"]
    elif "HTTP 404" not in existing.stderr:
        raise RuntimeError("Cannot safely inspect existing private candidate evidence")
    written=json.loads(run("gh","api","--method","PUT",
                           f"repos/{DATA_REPO}/contents/{PRIVATE_PATH}",
                           "--input","-",input=json.dumps(body)))
    # Read back the exact immutable commit returned by the write, not an
    # eventually consistent default-branch view of the mutable 'latest' path.
    # This also prevents a concurrent newer run from being mistaken for ours.
    commit_sha=(written.get("commit") or {}).get("sha")
    content_sha=(written.get("content") or {}).get("sha")
    if not all(isinstance(v,str) and len(v)==40
               and all(c in "0123456789abcdefABCDEF" for c in v)
               for v in (commit_sha,content_sha)):
        raise RuntimeError("Private candidate evidence write has no immutable readback reference")
    remote=json.loads(run("gh","api",
                          f"repos/{DATA_REPO}/contents/{PRIVATE_PATH}?ref={commit_sha}"))
    if remote.get("sha")!=content_sha or remote.get("encoding")!="base64":
        raise RuntimeError("Independent persisted candidate evidence blob identity mismatch")
    try:
        saved=base64.b64decode(remote["content"])
    except (KeyError,TypeError,ValueError) as exc:
        raise RuntimeError("Independent persisted candidate evidence is unreadable") from exc
    if saved!=raw:
        raise RuntimeError("Independent persisted candidate comparison readback mismatch")
    return hashlib.sha256(raw).hexdigest()


def main():
    cert=validate_certificate()
    base=ROOT/".cache/tbt"
    candidate=base/"model/model.joblib"
    report=json.loads((base/"model/training_report.json").read_text())
    evidence=make_evidence(cert,report,candidate)
    # Candidate upload must survive an independent PRIVATE release download.
    # Do not present local training output as a persisted model artifact.
    from release_store import ReleaseStore
    from tbt.models.artifact import load_model
    remote=base/"training-backup/candidate-persisted-readback"
    store=ReleaseStore(DATA_REPO,cert["candidate_tag"],remote)
    store.download(
        extra_names=("model.joblib","training_report.json","promotion_history.json"),
        required_names=("model.joblib","training_report.json","promotion_history.json"),
        require_bundle_manifest=True,
    )
    if hashlib.sha256((remote/"model.joblib").read_bytes()).hexdigest()!=evidence["candidate_sha256"]:
        raise RuntimeError("Published candidate binary differs from fitted local artifact")
    if (remote/"training_report.json").read_bytes()!=(base/"model/training_report.json").read_bytes():
        raise RuntimeError("Published candidate training report differs from local results")
    loaded=load_model(str(remote/"model.joblib"))
    if not loaded.fitted or loaded.version!=evidence["candidate_version"]:
        raise RuntimeError("Published candidate model is unfitted or has wrong version")
    evidence["candidate_remote_readback_verified"]=True
    digest=persist_verified(evidence)
    out=base/"training-backup/frozen-candidate-evaluation.json"
    out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps({"status":"EVALUATED_NOT_DEPLOYED",
                      "candidate":evidence["candidate_version"],
                      "champion":evidence["champion_version"],
                      "holdout_n":evidence["comparison"]["sample_size"],
                      "evidence_sha256":digest}))


if __name__=="__main__":
    main()
