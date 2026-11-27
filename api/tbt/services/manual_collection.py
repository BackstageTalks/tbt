"""One durable, admin-requested Tennis API collection at a time."""

import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from .admin_storage import AdminStorageUnavailable, UI_TABLE, _storage_not_found, _table
from ..providers.shared_budget import SharedBudgetUnavailable, status as budget_status

AREAS = {
    "statistics": ("Štatistiky zápasov", "Chýbajúce štatistiky celého zápasu a setov vrátane servisu, returnu, es a dvojchýb."),
    "break-points": ("Brejkbaly", "Cielené doplnenie chýbajúcich údajov o brejkbaloch."),
    "extras": ("Detail zápasu", "Chýbajúce doplnkové údaje z detailu zápasu."),
    "identity": ("Identifikátory zápasov", "Dohľadanie a overenie chýbajúcich identifikátorov zápasov u poskytovateľa."),
}
MAX_REQUESTS = 500
DEFAULT_REQUESTS = 100
LOOKBACK_DAYS = 365
QUEUE_TTL = timedelta(minutes=90)
PARTITION = "manual-api-collection"
ROW = "latest"
RUN_TITLE = "BlinQ manual API collection "
ACTIVE = {"queued", "waiting_for_budget", "dispatching", "running"}


class CollectionConflict(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _read():
    try:
        entity = _table(UI_TABLE).get_entity(partition_key=PARTITION, row_key=ROW)
        return json.loads(entity["payload"]), entity.metadata["etag"]
    except Exception as exc:
        if _storage_not_found(exc):
            return None, None
        raise AdminStorageUnavailable("Stav ručného zberu nie je dostupný.") from exc


def _store(item, etag):
    from azure.core import MatchConditions

    entity = {"PartitionKey": PARTITION, "RowKey": ROW,
              "payload": json.dumps(item, ensure_ascii=False, allow_nan=False)}
    try:
        table = _table(UI_TABLE)
        if etag is None:
            table.create_entity(entity)
        else:
            table.update_entity(entity, mode="merge", etag=etag,
                                match_condition=MatchConditions.IfNotModified)
    except Exception as exc:
        if getattr(exc, "status_code", None) in (409, 412):
            raise CollectionConflict("Stav zberu sa zmenil. Obnov stav.") from exc
        raise AdminStorageUnavailable("Stav ručného zberu sa nepodarilo uložiť.") from exc


def _remaining():
    budget = budget_status()
    return min(budget["global_remaining"], budget["remaining"]["history"])


def _public(item):
    if item is None:
        return None
    return {key: value for key, value in item.items() if key != "actor"}


def status():
    item, _ = _read()
    try:
        remaining = _remaining()
    except SharedBudgetUnavailable:
        remaining = None
    return {
        "areas": [{"id": key, "label": label, "description": description}
                  for key, (label, description) in AREAS.items()],
        "lookback_days": LOOKBACK_DAYS,
        "max_requests": MAX_REQUESTS,
        "default_requests": DEFAULT_REQUESTS,
        "remaining": remaining,
        "collection": _public(item),
        "can_start": remaining is not None and remaining > 0 and (
            item is None or item["state"] not in ACTIVE),
    }


def start(payload, actor):
    if not isinstance(payload, dict) or set(payload) != {"area", "max_requests"}:
        raise ValueError("Vyber oblasť a limit požiadaviek.")
    area, cap = payload["area"], payload["max_requests"]
    if not isinstance(area, str) or area not in AREAS:
        raise ValueError("Vyber podporovanú oblasť zberu.")
    if type(cap) is not int or not 1 <= cap <= MAX_REQUESTS:
        raise ValueError(f"Limit musí byť celé číslo od 1 do {MAX_REQUESTS}.")
    current, etag = _read()
    if current and current["state"] in ACTIVE:
        raise CollectionConflict("Ručný zber už čaká na spustenie alebo prebieha.")
    if cap > _remaining():
        raise CollectionConflict("Zvolený limit presahuje dostupnú kvótu pre históriu.")
    item = {
        "id": "api-" + secrets.token_hex(12),
        "actor": str(actor)[:128],
        "area": area,
        "max_requests": cap,
        "created_at": _now().isoformat(timespec="seconds"),
        "state": "queued",
    }
    _store(item, etag)
    return _public(item)


def workflow_inputs(item):
    area = item["area"]
    return {
        "request_id": item["id"],
        "mode": "statistics" if area == "break-points" else area,
        "break_points_focus": "true" if area == "break-points" else "false",
        "lookback_days": str(LOOKBACK_DAYS),
        "max_requests": str(item["max_requests"]),
        "promote": "false",
    }


def worker_status():
    item, _ = _read()
    return _public(item) if item and item["state"] in ACTIVE else None


def sync(payload):
    if (not isinstance(payload, dict) or set(payload) != {"id", "run"}
            or not re.fullmatch(r"api-[0-9a-f]{24}", str(payload["id"]))):
        raise ValueError("Invalid collection observation")
    item, etag = _read()
    if not item or item["id"] != payload["id"] or item["state"] not in ACTIVE:
        return {"pending": None}

    run = payload["run"]
    if run is not None:
        if (not isinstance(run, dict) or run.get("display_title") != RUN_TITLE + item["id"]
                or type(run.get("id")) is not int or run["id"] <= 0
                or run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
                or type(run.get("status")) is not str):
            raise ValueError("Invalid collection run")
        if item.get("run_id", run["id"]) != run["id"]:
            raise CollectionConflict("Identita behu sa zmenila.")
        item.update(run_id=run["id"], state="running")
        if run["status"] == "completed":
            item["state"] = "completed" if run.get("conclusion") == "success" else "failed"
        _store(item, etag)
        return {"pending": None}

    if item["state"] not in {"queued", "waiting_for_budget"}:
        # A claimed dispatch may have reached GitHub despite a lost response.
        return {"pending": None}
    if _now() - datetime.fromisoformat(item["created_at"]) > QUEUE_TTL:
        item["state"] = "expired"
    else:
        try:
            available = _remaining()
        except SharedBudgetUnavailable:
            available = 0
        item["state"] = "dispatching" if available >= item["max_requests"] else "waiting_for_budget"
    _store(item, etag)
    return {"pending": _public(item) if item["state"] == "dispatching" else None}
