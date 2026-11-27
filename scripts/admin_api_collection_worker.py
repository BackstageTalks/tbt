"""Dispatch approved manual collection through the existing Actions worker."""

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tbt.services.manual_collection import RUN_TITLE, workflow_inputs
from tbt.services.model_training import APP, github

ORIGIN = "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"
WORKFLOW = f"{APP}/actions/workflows/data.yml"
RUN_FIELDS = ("id", "status", "conclusion", "display_title", "head_branch", "event")


def sync(payload=None):
    if os.environ["BLINQ_BASE_URL"].rstrip("/") != ORIGIN:
        raise RuntimeError("Unexpected BlinQ Admin deployment")
    token = os.environ["BLINQ_LIVE_WORKER_TOKEN"]
    if not token:
        raise RuntimeError("Missing signed worker token")
    req = Request(
        ORIGIN + "/api/v1/internal/api-collection-sync",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", "X-Blinq-Worker-Token": token},
    )
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def find_run(item):
    if item.get("run_id"):
        return github(f"{APP}/actions/runs/{item['run_id']}")
    query = {"branch": "main", "event": "workflow_dispatch",
             "created": ">=" + item["created_at"], "per_page": 100}
    for page in range(1, 11):
        runs = github(f"{WORKFLOW}/runs?" + urlencode({**query, "page": page}))["workflow_runs"]
        for run in runs:
            if run.get("display_title") == RUN_TITLE + item["id"]:
                return run
        if len(runs) < 100:
            return None
    raise RuntimeError("Could not verify collection run within the GitHub result window")


def main():
    try:
        item = sync()["collection"]
    except HTTPError as exc:
        if exc.code != 404:
            raise
        print("Manual API collection: endpoint not deployed yet.")
        return
    if not item:
        return
    run = None if item["state"] in {"queued", "waiting_for_budget"} else find_run(item)
    observation = {key: run.get(key) for key in RUN_FIELDS} if run else None
    pending = sync({"id": item["id"], "run": observation})["pending"]
    if pending:
        # The durable claim has already succeeded. Never retry this POST.
        github(f"{WORKFLOW}/dispatches", {"ref": "main", "inputs": workflow_inputs(pending)})
        print("Manual API collection dispatch accepted:", pending["id"], flush=True)


if __name__ == "__main__":
    main()
