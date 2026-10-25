"""Process at most one signed Admin Model Lab command using trusted Actions.

Only bounded, pre-existing main workflows are allowed. Never auto-promote a
model or call tennis providers. Ambiguous dispatches remain permanently claimed.
"""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from tbt.services.model_training import APP, TrainingBlocked, github, inspect
from tbt.services.model_lab import collect_status, WORKFLOWS


def sync(snapshot):
    base = os.environ["BLINQ_BASE_URL"].rstrip("/")
    if base != "https://agreeable-sky-011a7fe10.7.azurestaticapps.net":
        raise RuntimeError("Unexpected Model Lab Admin deployment")
    token = os.environ["BLINQ_LIVE_WORKER_TOKEN"]
    if not token:
        raise RuntimeError("Missing signed worker token")
    req = Request(
        base + "/api/v1/internal/model-lab-sync",
        data=json.dumps(snapshot, allow_nan=False).encode(),
        headers={"Content-Type": "application/json", "X-Blinq-Worker-Token": token},
        method="POST",
    )
    with urlopen(req, timeout=45) as response:
        result = json.load(response)
    if result.get("stored") is not True:
        raise RuntimeError("Model Lab Admin did not confirm durable state")
    return result


def dispatch(pending):
    operation = pending["action"]
    marker = pending["id"]
    if operation not in WORKFLOWS or len(marker) != 24:
        raise RuntimeError("Unknown Model Lab operation")
    # Recheck current lock and inflight training before any dispatch.
    current = collect_status()
    if not current["can_start"] or not inspect()["can_start"]:
        raise TrainingBlocked("Model Lab or candidate training queue changed after claim; dispatch blocked")
    if current["active_sha256"] != pending["expected_candidate_sha256"]:
        raise TrainingBlocked("Active shadow candidate changed after claim")
    if current["champion_sha256"] != pending["expected_champion_sha256"]:
        raise TrainingBlocked("Champion changed after claim")
    preflight = sync({**current, "dispatch_request_id": marker})
    if preflight.get("dispatch_ready") is not True:
        raise TrainingBlocked("Durable Admin queue did not confirm this claimed dispatch")
    inputs = {"request_id": marker}
    if operation == "import_drive":
        inputs["catchup_remaining"] = "0"  # One existing guarded 100-file batch.
    elif operation == "activate_shadow":
        if not any(c["tag"] == pending["source_tag"]
                   and c["sha256"] == pending["source_sha256"]
                   for c in current["candidates"]):
            raise TrainingBlocked("Frozen release digest changed after claim")
        inputs.update({
            "source_tag": pending["source_tag"],
            "expected_candidate_sha256": pending["expected_candidate_sha256"],
        })
    elif operation == "promote_production":
        if not any(c["tag"] == pending["source_tag"] and c["sha256"] == pending["source_sha256"]
                   for c in current["candidates"]):
            raise TrainingBlocked("Production source changed after approval")
        inputs.update({key: pending[key] for key in (
            "source_tag", "source_sha256", "expected_champion_sha256")})
        inputs["calibration_override"] = "true"
    # refresh_tests is the existing read-only Admin calibration monitor.
    github(f"{APP}/actions/workflows/{WORKFLOWS[operation]}/dispatches",
           {"ref": "main", "inputs": inputs})
    print("Model Lab one-shot dispatch accepted, run identity pending verification:",
          operation, marker, flush=True)



def admin_model_lab_endpoint_ready(base_url=None, open_url=urlopen):
    """Read-only origin probe of the *actual* deployed admin route.

    Frequent unrelated commits can cancel the GitHub workflow after Azure has
    already published the API. Do not rely on CI run labels or checkout SHA.
    Require the real protected route to deny an anonymous GET with the exact
    expected JSON 401 response before sending any signed request.
    """
    base = (base_url or os.environ["BLINQ_BASE_URL"]).rstrip("/")
    if base != "https://agreeable-sky-011a7fe10.7.azurestaticapps.net":
        raise RuntimeError("Unexpected Model Lab Admin deployment")
    req = Request(base + "/api/v1/admin/model-lab", method="GET")
    try:
        with open_url(req, timeout=20):
            raise RuntimeError("Admin-only Model Lab endpoint accepted anonymous request")
    except HTTPError as error:
        if error.code == 404:
            return False
        if error.code != 401:
            raise RuntimeError(f"Unexpected Model Lab Admin probe HTTP {error.code}") from error
        try:
            body = json.loads(error.read(1024))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Invalid unauthorized Model Lab response") from exc
        if not isinstance(body, dict) or body.get("error") != "unauthorized":
            raise RuntimeError("Admin route did not prove protected access")
        return True


def main():
    if not admin_model_lab_endpoint_ready():
        print("MODEL_LAB_DEFERRED: protected Admin route is not deployed yet", flush=True)
        return
    snapshot = collect_status()
    result = sync(snapshot)
    pending = result.get("pending")
    if pending:
        dispatch(pending)
    else:
        print("Model Lab status synchronized; no unclaimed operation", flush=True)


if __name__ == "__main__":
    main()
