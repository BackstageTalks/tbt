"""Synchronize admin status and consume at most one durable training request."""
import json
import os
from urllib.request import Request, urlopen
from tbt.services.model_training import collect_status, inspect, github, APP, WORKFLOW


def sync(snapshot, claim=False):
    base = os.environ["BLINQ_BASE_URL"].rstrip("/")
    if base != "https://agreeable-sky-011a7fe10.7.azurestaticapps.net":
        raise RuntimeError("Unexpected admin deployment")
    req = Request(base + "/api/v1/internal/model-training-sync",
        data=json.dumps({"snapshot": snapshot, "claim": claim}).encode(),
        headers={"Content-Type": "application/json", "X-Blinq-Worker-Token": os.environ["BLINQ_LIVE_WORKER_TOKEN"]}, method="POST")
    with urlopen(req, timeout=45) as result:
        response = json.load(result)
    if response.get("stored") is not True:
        raise RuntimeError("Admin snapshot readback not confirmed")
    return response


def main():
    state = collect_status()
    response = sync(state, claim=True)
    if response.get("claim_blocked"):
        raise RuntimeError("Request already claimed or storage uncertain; operator reconciliation required")
    pending = response.get("pending")
    if pending:
        current = inspect()
        if not current["can_start"] or current["base"] != pending["base"]:
            raise RuntimeError("Training changed after claim; no dispatch, manual reconciliation required")
        if pending["profile"] not in {"standard", "top-7.2.1"}:
            raise RuntimeError("Invalid requested profile")
        github(f"{APP}/actions/workflows/{WORKFLOW}/dispatches", {
            "ref": "main", "inputs": {"training_profile": pending["profile"], "auto_shadow": "true"}})
        print("One protected training dispatch accepted; actual run will be verified on next sync")
    else:
        print("Admin snapshot persisted and read back; no new request dispatched")


if __name__ == "__main__":
    main()
