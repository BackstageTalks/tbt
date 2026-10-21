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
    token = os.getenv("BLINQ_TRAINING_DISPATCH_TOKEN" if payload is not None else "BLINQ_TRAINING_GITHUB_TOKEN", "").strip()
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


def collect_status():
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


PARTITION = "model-training-queue"


def row(key):
    try:
        return _table(UI_TABLE).get_entity(partition_key=PARTITION, row_key=key)
    except KeyError:
        return None
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise AdminStorageUnavailable("Training storage unavailable") from exc


def save(key, payload):
    try:
        _table(UI_TABLE).upsert_entity({"PartitionKey": PARTITION, "RowKey": key,
            "payload": json.dumps(payload, ensure_ascii=False)}, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Training storage unavailable") from exc


def status():
    stored = row("snapshot")
    if not stored:
        raise TrainingUnavailable("Čaká sa na prvú synchronizáciu tréningu.")
    result = json.loads(stored["payload"])
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(result["observed_at"])).total_seconds()
    if age < -60 or age > 5400:
        result.update(can_start=False, reason="Stav je neaktuálny. Čaká sa na synchronizáciu.")
    if row("request-" + result["base"]):
        result.update(can_start=False, reason="Požiadavka bola uložená. Čaká sa na potvrdenie behu; neposielaj ju znova.")
        claim = row("claim-" + result["base"])
        if claim and (datetime.now(timezone.utc) - datetime.fromisoformat(claim["created_at"])).total_seconds() > 600:
            result["reason"] = "Worker prevzal požiadavku, ale beh ešte nie je potvrdený. Vyžaduje sa kontrola; ďalší tréning je blokovaný."
    return result


def start(payload, actor):
    if not isinstance(payload, dict) or set(payload) - {"profile"}:
        raise ValueError("Neplatná požiadavka na tréning.")
    profile = payload.get("profile", "top-7.2.1")
    if profile not in {"standard", "top-7.2.1"}:
        raise ValueError("Neplatný tréningový profil.")
    # Both Admin entrypoints share the same queue guard. A candidate training
    # request must not leapfrog an active Drive import or shadow activation.
    # Lazy import avoids a module cycle; an unavailable table fails closed.
    from .model_lab import _row as lab_row
    if lab_row("active") is not None:
        raise TrainingBlocked("Model Factory má rozpracovanú operáciu. Obnov stav.")
    current = status()
    if not current["can_start"]:
        raise TrainingBlocked(current["reason"])
    try:
        _table(UI_TABLE).create_entity({"PartitionKey": PARTITION,
            "RowKey": "request-" + current["base"], "actor": str(actor),
            "profile": profile, "base": current["base"],
            "created_at": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        raise TrainingBlocked("Požiadavka už existuje alebo úložisko nie je dostupné. Obnov stav.") from exc
    return {"state": "QUEUED", "message": "Požiadavka uložená. Worker ju prevezme pri najbližšej kontrole (bežne do 30 minút). Obnov stav pre potvrdenie behu."}


def sync(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshot"), dict):
        raise ValueError("Invalid worker snapshot")
    snapshot = payload["snapshot"]
    if not isinstance(snapshot.get("can_start"), bool) or not str(snapshot.get("base", "")).isdigit() and snapshot.get("base") != "initial":
        raise ValueError("Invalid snapshot state")
    snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
    save("snapshot", snapshot)
    # Independent durable readback, not merely an acknowledged write.
    if json.loads(row("snapshot")["payload"]) != snapshot:
        raise AdminStorageUnavailable("Snapshot readback mismatch")
    request = row("request-" + snapshot["base"])
    pending = None
    if request and snapshot["can_start"] and payload.get("claim") is True:
        try:
            _table(UI_TABLE).create_entity({"PartitionKey": PARTITION,
                "RowKey": "claim-" + snapshot["base"],
                "created_at": datetime.now(timezone.utc).isoformat()})
        except Exception:
            # A prior claim or unknown store result must never redispatch.
            return {"stored": True, "pending": None, "claim_blocked": True}
        pending = {"base": request["base"], "profile": request["profile"]}
    return {"stored": True, "pending": pending}
