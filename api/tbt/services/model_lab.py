"""Fail-closed Admin operations for bounded CDB import, read-only tests and shadow.

Admin never holds GitHub credentials. An existing trusted Actions worker owns
all dispatches. One durable guard permits at most one Lab operation in flight;
an atomic one-shot claim prevents retry after ambiguous dispatch outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import secrets
import os
from pathlib import Path
import subprocess
import tempfile

from .admin_storage import _table, UI_TABLE, AdminStorageUnavailable
from .model_training import APP, DATA, TrainingBlocked, TrainingUnavailable, github, inspect, status as training_status

PARTITION = "model-lab-queue"
WORKFLOWS = {
    "prepare_inputs": "model-factory-preflight.yml",
    "import_drive": "cdb-drive-inbox.yml",
    "refresh_tests": "model-calibration-monitor.yml",
    "audit_shadow": "model-shadow-evaluation-readonly.yml",
    "activate_shadow": "activate-shadow-candidate.yml",
}
REQUIRED_ASSETS = {"model.joblib", "training_report.json", "_tbt_bundle_manifest.json"}
CANDIDATE_TAG = re.compile(r"blinq-candidate-frozen-[0-9]+-[0-9]+\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MARKER = re.compile(r"[0-9a-f]{24}\Z")


def _utcnow():
    return datetime.now(timezone.utc)


def _row(key):
    try:
        return _table(UI_TABLE).get_entity(partition_key=PARTITION, row_key=key)
    except KeyError:
        return None
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise AdminStorageUnavailable("Model Lab storage unavailable") from exc


def _put(key, data):
    try:
        _table(UI_TABLE).upsert_entity({
            "PartitionKey": PARTITION, "RowKey": key,
            "payload": json.dumps(data, ensure_ascii=False, allow_nan=False),
        }, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Model Lab storage unavailable") from exc
    read = _row(key)
    if not read or json.loads(read["payload"]) != data:
        raise AdminStorageUnavailable("Model Lab readback mismatch")


def _create(key, data):
    try:
        _table(UI_TABLE).create_entity({
            "PartitionKey": PARTITION, "RowKey": key,
            "payload": json.dumps(data, ensure_ascii=False, allow_nan=False),
        })
    except Exception as exc:
        raise TrainingBlocked("Operácia už beží alebo úložisko nie je dostupné. Obnov stav.") from exc
    read = _row(key)
    if not read or json.loads(read["payload"]) != data:
        raise AdminStorageUnavailable("Model Lab claim readback mismatch")


def _json(key):
    item = _row(key)
    return json.loads(item["payload"]) if item else None


def _age(value):
    try:
        return (_utcnow() - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds()
    except (ValueError, TypeError, AttributeError):
        return 10**9


def _digest(release):
    assets = {x.get("name"): x for x in release.get("assets", []) if x.get("size", 0) > 0}
    if not REQUIRED_ASSETS <= assets.keys():
        return ""
    digest = str(assets["model.joblib"].get("digest") or "")
    return digest[7:] if digest.startswith("sha256:") and SHA.fullmatch(digest[7:]) else ""


def _read_preflight_report(run: dict, artifacts: list[dict]) -> dict:
    """Trusted Actions worker: independently download and validate audit bytes."""
    run_id = run.get("id")
    head_sha = str(run.get("head_sha") or "")
    if not isinstance(run_id, int) or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise TrainingUnavailable("Unpinned preflight run")
    name = f"model-factory-preflight-{run_id}"
    selected = [a for a in artifacts if a.get("name") == name and
                a.get("expired") is False and int(a.get("size_in_bytes") or 0) > 0]
    if len(selected) != 1:
        raise TrainingUnavailable("Preflight report artifact not independently available")
    token = os.environ.get("BLINQ_TRAINING_GITHUB_TOKEN", "").strip()
    if not token:
        raise TrainingUnavailable("Trusted preflight artifact reader has no GitHub token")
    with tempfile.TemporaryDirectory(prefix="blinq-preflight-") as directory:
        env = dict(os.environ, GH_TOKEN=token)
        proc = subprocess.run(
            ["gh", "run", "download", str(run_id), "-R", APP, "-n", name, "-D", directory],
            capture_output=True, text=True, timeout=120, env=env)
        if proc.returncode:
            raise TrainingUnavailable("Cannot independently download preflight report")
        path = Path(directory) / "report.json"
        if not path.is_file() or path.stat().st_size > 32768:
            raise TrainingUnavailable("Preflight report missing or unexpectedly large")
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise TrainingUnavailable("Invalid preflight report bytes") from exc
    if (not isinstance(report, dict) or report.get("schema") != 1 or
            report.get("status") != "READ_ONLY_PREFLIGHT_COMPLETE_NOT_FROZEN" or
            report.get("code_sha") != head_sha or
            not SHA.fullmatch(str(report.get("canonical_manifest_sha256") or ""))):
        raise TrainingUnavailable("Preflight artifact failed source identity validation")
    tours = report.get("tours")
    if not isinstance(tours, dict) or set(tours) != {"atp", "wta"}:
        raise TrainingUnavailable("Incomplete ATP/WTA report")
    compact = {}
    for tour in ("atp", "wta"):
        row = tours[tour]
        n = row.get("eligible_matches")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise TrainingUnavailable("Invalid ATP/WTA match count")
        counts = row.get("coverage_counts")
        if not isinstance(counts, dict):
            raise TrainingUnavailable("Invalid ATP/WTA stat coverage")
        verified_counts = {}
        for key in ("rank_pair", "serve", "return", "break_points", "stat_rows"):
            value = counts.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= n:
                raise TrainingUnavailable("Invalid per-tour stat count")
            verified_counts[key] = value
        compact[tour] = {"eligible_matches": n, "coverage_counts": verified_counts}
    if (sum(row["eligible_matches"] for row in compact.values()) != report.get("eligible_rows") or
            report["eligible_rows"] < 500000):
        raise TrainingUnavailable("Preflight total count mismatch")
    return {"tours": compact, "eligible_rows": report["eligible_rows"],
            "excluded_rows": report.get("excluded_rows"),
            "manifest_sha256": report["canonical_manifest_sha256"],
            "source_run_id": run_id}


def collect_status(read=github):
    """Worker-only GitHub fetch. No provider calls and no CDB writes."""
    # Prove private data repository access before treating missing evidence as empty.
    read(DATA)
    current = read(f"{DATA}/releases/tags/tbt-model-candidate-v1")
    production = read(f"{DATA}/releases/tags/tbt-model-production-v1")
    active_sha, champion_sha = _digest(current), _digest(production)
    if not active_sha or not champion_sha:
        raise TrainingUnavailable("Current model release is missing verified asset digests")
    releases = read(f"{DATA}/releases?per_page=100")
    candidates = []
    for item in releases:
        tag = str(item.get("tag_name") or "")
        if CANDIDATE_TAG.fullmatch(tag):
            digest = _digest(item)
            if digest:
                candidates.append({
                    "tag": tag, "sha256": digest,
                    "url": item.get("html_url", ""),
                    "label": "Uložený model, pred aktiváciou sa znovu overí",
                })
    runs = {}
    busy = False
    for action, workflow in WORKFLOWS.items():
        raw = read(f"{APP}/actions/workflows/{workflow}/runs?per_page=15")
        entries = []
        inspected_preflight = False
        for item in raw.get("workflow_runs", []):
            record = {k: item.get(k) for k in
                      ("id", "status", "conclusion", "html_url", "display_title", "created_at", "head_sha")}
            if (action == "prepare_inputs" and not inspected_preflight and
                    item.get("status") == "completed" and item.get("conclusion") == "success"):
                inspected_preflight = True
                artifacts = read(f"{APP}/actions/runs/{item['id']}/artifacts?per_page=100")
                try:
                    record["preflight_report"] = _read_preflight_report(
                        item, artifacts.get("artifacts", []))
                    record["artifact_verified"] = True
                except TrainingUnavailable:
                    # Old/expired or unverified bytes must not break every future
                    # worker sync; the preparation remains NOT verified.
                    record["artifact_verified"] = False
            entries.append(record)
            if item.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
                busy = True
        runs[action] = entries
    training = inspect(read=read)
    available = not busy and training["can_start"]
    return {
        "observed_at": _utcnow().isoformat(), "can_start": available,
        "reason": ("Iný import, test alebo shadow aktivácia už prebieha." if busy
                   else training["reason"]),
        "active_sha256": active_sha, "champion_sha256": champion_sha,
        "candidates": candidates, "runs": runs,
    }


def _operation_view(request, snapshot):
    action = request["action"]
    marker = request["id"]
    matches = [
        r for r in snapshot.get("runs", {}).get(action, [])
        if r.get("display_title") and marker in str(r["display_title"])
    ]
    selected = matches[0] if matches else None
    claimed = _json("claim-" + marker) is not None
    return {
        "id": marker, "action": action, "source_tag": request.get("source_tag"),
        "created_at": request["created_at"],
        "state": ("RUNNING" if selected and selected.get("status") != "completed"
                  else "COMPLETED_PENDING_VERIFICATION" if selected
                  else "DISPATCH_UNCONFIRMED" if claimed else "QUEUED"),
        "run": selected,
    }


def status():
    snapshot = _json("snapshot")
    if not snapshot:
        raise TrainingUnavailable("Model Lab čaká na prvú synchronizáciu GitHub workerom.")
    snapshot["can_start"] = bool(snapshot.get("can_start"))
    if _age(snapshot.get("observed_at")) > 5400 or _age(snapshot.get("observed_at")) < -60:
        snapshot.update(can_start=False, reason="Neaktuálny stav, operácia je zablokovaná.")
    active = _json("active")
    if active:
        snapshot.update(can_start=False, reason="Operácia už beží alebo čaká na nezávislé overenie.")
    snapshot["operation"] = _operation_view(active, snapshot) if active else None
    snapshot["last_operation"] = _json("last")
    snapshot["last_preflight"] = _json("last_preflight")
    return snapshot


def start(payload, actor):
    if not isinstance(payload, dict) or set(payload) - {"action", "source_tag"}:
        raise ValueError("Nepodporovaná operácia.")
    action = payload.get("action")
    if action not in WORKFLOWS:
        raise ValueError("Nepovolená operácia.")
    if action != "activate_shadow" and "source_tag" in payload:
        raise ValueError("Tag modelu sa pri tejto operácii nesmie zadávať.")
    current = status()
    training = training_status()
    if not training.get("can_start"):
        raise TrainingBlocked("Ochranná fronta tréningu je obsadená alebo neaktuálna.")
    if not current["can_start"]:
        raise TrainingBlocked(current["reason"])
    tag = None
    digest = None
    if action == "activate_shadow":
        tag = payload.get("source_tag")
        if not isinstance(tag, str) or not CANDIDATE_TAG.fullmatch(tag):
            raise ValueError("Vyber existujúceho zmrazeného kandidáta.")
        model = next((r for r in current["candidates"] if r["tag"] == tag), None)
        if model is None:
            raise ValueError("Kandidát nie je v overenom zozname modelov.")
        digest = model["sha256"]
        if digest == current["active_sha256"]:
            raise TrainingBlocked("Tento model už môže byť aktívnym kandidátom. Skontroluj shadow report.")
    request = {
        "id": secrets.token_hex(12), "action": action,
        "actor": str(actor)[:128], "created_at": _utcnow().isoformat(),
        "source_tag": tag, "source_sha256": digest,
        "expected_candidate_sha256": current["active_sha256"],
        "expected_champion_sha256": current["champion_sha256"],
        "snapshot_at": current["observed_at"],
    }
    _create("active", request)
    return {"state": "QUEUED", "id": request["id"],
            "message": "Požiadavka je uložená. Worker ju spustí raz; priebeh sleduj v Model Lab."}


def _find_run(request, snapshot):
    return next((r for r in snapshot["runs"].get(request["action"], [])
                 if request["id"] in str(r.get("display_title") or "")
                 and _age(r.get("created_at")) <= _age(request["created_at"]) + 90),
                None)


def _finalize(request, run, snapshot):
    if run.get("conclusion") != "success":
        # Unknown or failed write must not silently reopen the queue.
        _put("last", {"id": request["id"], "action": request["action"],
                      "state": "FAILED_NEEDS_REVIEW", "run": run})
        return
    if (request["action"] == "prepare_inputs" and
            (run.get("artifact_verified") is not True or
             not isinstance(run.get("preflight_report"), dict))):
        raise TrainingBlocked("Preflight report was not independently retained as a GitHub artifact")
    if request["action"] == "activate_shadow":
        expected = request["source_sha256"]
        source = next((c for c in snapshot["candidates"]
                       if c["tag"] == request["source_tag"] and c["sha256"] == expected), None)
        if not source or snapshot["active_sha256"] != expected:
            raise TrainingBlocked("Candidate readback checksum mismatch; manual reconciliation required")
        if snapshot["champion_sha256"] != request["expected_champion_sha256"]:
            raise TrainingBlocked("Production changed unexpectedly; manual reconciliation required")
    result = {
        "id": request["id"], "action": request["action"],
        "state": "WORKFLOW_VERIFIED", "run": run,
        "verified_at": _utcnow().isoformat(),
        # A successful bounded import run is not proof that new eligible rows existed.
        "note": ("Skontroluj počet nových CDB riadkov v importe."
                 if request["action"] == "import_drive" else
                 "Predtréningový audit prešiel; snapshot pre fit sa vytvorí až pri tréningu."
                 if request["action"] == "prepare_inputs" else
                 "Zápis kandidáta a kontrola produkcie boli overené."
                 if request["action"] == "activate_shadow" else
                 "Testovací snapshot bol synchronizovaný."),
    }
    _put("last", result)
    if request["action"] == "prepare_inputs":
        _put("last_preflight", result)
    try:
        _table(UI_TABLE).delete_entity(partition_key=PARTITION, row_key="active")
    except Exception as exc:
        raise AdminStorageUnavailable("Model Lab guard cleanup failed; operator review required") from exc
    if _row("active"):
        raise AdminStorageUnavailable("Model Lab guard still present after verified success")


def sync(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("can_start"), bool):
        raise ValueError("Invalid Model Lab worker snapshot")
    if not SHA.fullmatch(str(snapshot.get("active_sha256") or "")):
        raise ValueError("Invalid active model SHA")
    if not SHA.fullmatch(str(snapshot.get("champion_sha256") or "")):
        raise ValueError("Invalid champion model SHA")
    if _age(snapshot.get("observed_at")) > 120 or _age(snapshot.get("observed_at")) < -60:
        raise ValueError("Stale Model Lab snapshot")
    snapshot = dict(snapshot)
    dispatch_id = snapshot.pop("dispatch_request_id", None)
    if dispatch_id is not None and not MARKER.fullmatch(str(dispatch_id)):
        raise ValueError("Invalid dispatch preflight marker")
    _put("snapshot", snapshot)
    active = _json("active")
    if dispatch_id is not None:
        # Run on the API host, where the durable Admin queue actually lives.
        # Actions workers deliberately have no Azure/Firestore credentials.
        ready = bool(
            active and active.get("id") == dispatch_id
            and _json("claim-" + dispatch_id)
            and snapshot["can_start"]
            and active["expected_candidate_sha256"] == snapshot["active_sha256"]
            and active["expected_champion_sha256"] == snapshot["champion_sha256"]
            and not _find_run(active, snapshot)
            and training_status().get("can_start")
        )
        if ready and active["action"] == "activate_shadow":
            ready = any(c["tag"] == active["source_tag"] and c["sha256"] == active["source_sha256"]
                        for c in snapshot["candidates"])
        return {"stored": True, "pending": None, "dispatch_ready": ready}
    if not active:
        return {"stored": True, "pending": None}
    marker = active.get("id")
    if not isinstance(marker, str) or not MARKER.fullmatch(marker):
        raise ValueError("Invalid operation marker")
    claimed = _json("claim-" + marker)
    if claimed:
        run = _find_run(active, snapshot)
        if run and run.get("status") == "completed":
            _finalize(active, run, snapshot)
        return {"stored": True, "pending": None}
    if not snapshot["can_start"]:
        return {"stored": True, "pending": None}
    if not training_status().get("can_start"):
        return {"stored": True, "pending": None}
    if _age(active["snapshot_at"]) > 5400:
        return {"stored": True, "pending": None}
    if active["expected_candidate_sha256"] != snapshot["active_sha256"]:
        return {"stored": True, "pending": None}
    if active["expected_champion_sha256"] != snapshot["champion_sha256"]:
        return {"stored": True, "pending": None}
    if active["action"] == "activate_shadow":
        source = next((c for c in snapshot["candidates"]
                       if c["tag"] == active["source_tag"]
                       and c["sha256"] == active["source_sha256"]), None)
        if source is None:
            return {"stored": True, "pending": None}
    _create("claim-" + marker, {"created_at": _utcnow().isoformat()})
    # At-most-once claim; if dispatch API times out, do not retry automatically.
    return {"stored": True, "pending": active}


def acknowledge_failed(payload):
    """Allow explicit admin unblocking only for a verified FAILED workflow."""
    if not isinstance(payload, dict) or set(payload) != {"action", "id"} or payload["action"] != "acknowledge_failed":
        raise ValueError("Invalid acknowledgement")
    active = _json("active")
    last = _json("last")
    if not active or not last or active["id"] != payload["id"] or last.get("id") != payload["id"] or last.get("state") != "FAILED_NEEDS_REVIEW":
        raise TrainingBlocked("No independently verified failed operation")
    # An importer or shadow activation may have failed after a partial write.
    # Browser acknowledgement is safe only for read-only refreshes.
    if active["action"] not in {"prepare_inputs", "refresh_tests", "audit_shadow"}:
        raise TrainingBlocked("Import alebo shadow zápis vyžaduje nezávislé overenie a ručnú rekonciliáciu.")
    snapshot = status()
    run = _find_run(active, snapshot)
    if not run or run.get("status") != "completed" or run.get("conclusion") == "success":
        raise TrainingBlocked("Run is not a verified failure")
    try:
        _table(UI_TABLE).delete_entity(partition_key=PARTITION, row_key="active")
    except Exception as exc:
        raise AdminStorageUnavailable("Cannot acknowledge failed operation") from exc
    return {"state": "FAILED_ACKNOWLEDGED", "message": "Neúspešný beh bol potvrdený; pred opakovaním skontroluj jeho dôvod."}
