"""Admin-only bridge to the existing protected training workflow."""
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .admin_storage import _table, UI_TABLE, AdminStorageUnavailable

APP = "BackstageTalks/tbt"
DATA = "BackstageTalks/tbt-data"
WORKFLOW = "protected-frozen-cdb-candidate.yml"


class TrainingUnavailable(RuntimeError):
    pass


class TrainingBlocked(RuntimeError):
    pass


def github(path, payload=None, missing_ok=False):
    token = os.getenv("BLINQ_TRAINING_GITHUB_TOKEN", "").strip()
    if not token:
        raise TrainingUnavailable("Tréning nie je nakonfigurovaný na serveri.")
    req = Request("https://api.github.com/repos/" + path,
                  data=json.dumps(payload).encode() if payload is not None else None,
                  headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json", "User-Agent": "BlinQ-Model-Lab"},
                  method="POST" if payload is not None else "GET")
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        if exc.code == 404 and missing_ok:
            return None
        raise TrainingUnavailable("GitHub požiadavku nepotvrdil. Stav treba obnoviť; neopakuj spustenie naslepo.") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise TrainingUnavailable("GitHub je nedostupný; výsledok požiadavky nie je potvrdený.") from exc


def inspect(read=github):
    runs = read(f"{APP}/actions/workflows/{WORKFLOW}/runs?per_page=10")["workflow_runs"]
    latest = runs[0] if runs else None
    busy = False
    for status in ("queued", "in_progress", "waiting", "pending", "requested"):
        busy = bool(read(f"{APP}/actions/workflows/{WORKFLOW}/runs?status={status}&per_page=1")["workflow_runs"]) or busy
    # Prove private repository access before accepting a missing ref.
    read(DATA)
    path = f"{DATA}/git/ref/tags/blinq-cdb-global-writer"
    first = read(path, missing_ok=True)
    second = read(path, missing_ok=True)
    locked = first is not None or second is not None
    base = str(latest["id"]) if latest else "initial"
    return {"runs": [{k: r.get(k) for k in ("id", "status", "conclusion", "head_sha", "html_url", "created_at")} for r in runs],
            "base": base, "can_start": not busy and not locked,
            "reason": "Tréning už beží alebo čaká." if busy else "Dátový zámok je obsadený. Po zlyhaní vyžaduje overenie vlastníka." if locked else "Pripravené na nový tréning."}


def status():
    result = inspect()
    if result["runs"]:
        run = result["runs"][0]
        jobs = github(f"{APP}/actions/runs/{run['id']}/jobs?per_page=100")
        result["active_steps"] = [step["name"] for job in jobs.get("jobs", [])
                                  for step in job.get("steps", []) if step.get("status") == "in_progress"]
    rows = github(f"{DATA}/releases?per_page=100")
    result["candidates"] = []
    for row in rows:
        if not row["tag_name"].startswith("blinq-candidate-frozen-"):
            continue
        assets = {a["name"] for a in row.get("assets", []) if a.get("size", 0) > 0}
        present = {"model.joblib", "training_report.json", "_tbt_bundle_manifest.json"} <= assets
        result["candidates"].append({"tag": row["tag_name"], "url": row["html_url"],
                                     "label": "Model uložený · kvalita neoverená" if present else "Nedokončený tréning"})
    result["candidate_scope"] = "Kandidáti z posledných 100 releases"
    return result


def start(payload, actor):
    if not isinstance(payload, dict) or set(payload) - {"profile"}:
        raise ValueError("Neplatná požiadavka na tréning.")
    profile = payload.get("profile", "top-7.2.1")
    if profile not in {"standard", "top-7.2.1"}:
        raise ValueError("Neplatný tréningový profil.")
    current = inspect()
    if not current["can_start"]:
        raise TrainingBlocked(current["reason"])
    sha = github(f"{APP}/commits/main")["sha"]
    # Atomic durable claim shared by all server workers. Retain on ambiguous
    # dispatch: never duplicate a potentially accepted request after timeout.
    try:
        _table(UI_TABLE).create_entity({"PartitionKey": "model-training-dispatch",
            "RowKey": current["base"], "actor": str(actor), "profile": profile,
            "observed_sha": sha, "created_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        raise TrainingBlocked("Požiadavku nemožno bezpečne rezervovať. Môže už byť odoslaná; obnov stav alebo skontroluj úložisko.") from exc
    github(f"{APP}/actions/workflows/{WORKFLOW}/dispatches", {"ref": "main", "inputs": {"training_profile": profile}})
    return {"state": "DISPATCHED_NOT_VERIFIED", "observed_sha": sha,
            "message": "Požiadavka odoslaná. Obnov stav pre potvrdenie behu a jeho verzie."}
