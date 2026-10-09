"""Persistent admin UI configuration and banner analytics.

The store prefers Azure Table Storage and can fall back to Firebase Firestore.
Firebase Auth remains the runtime identity provider; tennis history stays outside the identity layer.
On Azure Functions, AzureWebJobsStorage is used automatically unless
BLINQ_ADMIN_STORAGE_CONNECTION_STRING is supplied.
"""
from __future__ import annotations

from collections import defaultdict
import base64
import gzip
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .dashboard_kpis import ALLOWED_PERIODS


class AdminStorageUnavailable(RuntimeError):
    pass


UI_TABLE = "BlinQAdminConfig"
UI_HISTORY_PARTITION = "ui-config-history"
_UI_SNAPSHOT_ID = re.compile(r"^before-\d{8}T\d{12}Z-[a-f0-9]{8}$")
ANALYTICS_TABLE = "BlinQBannerAnalytics"
INSIGHTS_TABLE = "BlinQInsights"
INSIGHT_READS_TABLE = "BlinQInsightReads"
PROJECT_GROUPS_TABLE = "BlinQProjectGroups"
PROJECT_GROUP_MEMBERS_TABLE = "BlinQProjectGroupMembers"
_VALID_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_VALID_BANNER_SLOT = re.compile(r"^HERO_BANNER_[1-5]$")


def _valid_destination(value: object, *, allow_internal: bool = True) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if allow_internal:
        if text.startswith("#") and not text.startswith("##"):
            return True
        # Never accept protocol-relative //host links as internal paths.
        if text.startswith("/") and not text.startswith("//"):
            return True
    parsed = urlparse(text)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password


def _connection_string_source() -> tuple[str, str]:
    """Return the first configured durable-storage connection and its safe source name.

    A single general-purpose Azure Storage account can back admin config, INFO,
    LIVE alert history and media. Keeping the explicit admin
    setting first preserves separation when desired, while the unified/media
    aliases avoid an unnecessary outage when the same account is already
    configured for banner uploads.  Secrets are never returned by diagnostics.
    """
    candidates = (
        ("BLINQ_ADMIN_STORAGE_CONNECTION_STRING", os.getenv("BLINQ_ADMIN_STORAGE_CONNECTION_STRING")),
        ("BLINQ_STORAGE_CONNECTION_STRING", os.getenv("BLINQ_STORAGE_CONNECTION_STRING")),
        ("BLINQ_MEDIA_STORAGE_CONNECTION_STRING", os.getenv("BLINQ_MEDIA_STORAGE_CONNECTION_STRING")),
        ("AzureWebJobsStorage", os.getenv("AzureWebJobsStorage")),
    )
    for source, value in candidates:
        text = str(value or "").strip()
        if text:
            return text, source
    return "", ""


def _connection_string() -> str:
    return _connection_string_source()[0]


class _VersionedStorageEntity(dict):
    """Mapping compatible with Azure TableEntity's version metadata."""

    def __init__(self, data, version):
        super().__init__(data)
        self.metadata = {"etag": version}


class _StorageWriteConflict(Exception):
    status_code = 412


class _FirestoreTableAdapter:
    """Small Azure-Table-compatible adapter backed by Firebase Firestore.

    Azure Table Storage remains the preferred store when configured. Firestore is
    a zero-extra-secret fallback because BlinQ already has Firebase Admin
    credentials for Auth. Only the tiny subset of Table operations used by BlinQ
    is implemented here.
    """

    def __init__(self, name: str):
        try:
            from firebase_admin import firestore
            from .auth import firebase_app
            from ..config import settings
            app = firebase_app(settings)
            self._db = firestore.client(app=app)
        except Exception as exc:
            raise AdminStorageUnavailable(
                "Admin storage is not configured. Configure Azure storage or enable Firestore for the Firebase project."
            ) from exc
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "table"))[:80]
        self._collection = self._db.collection(f"blinq_{safe}")

    @staticmethod
    def _doc_id(partition_key: object, row_key: object) -> str:
        raw = f"{partition_key}\0{row_key}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get_entity(self, *, partition_key, row_key):
        snap = self._collection.document(self._doc_id(partition_key, row_key)).get()
        if not snap.exists:
            raise KeyError(str(row_key))
        return _VersionedStorageEntity(snap.to_dict() or {}, snap.update_time)

    def update_entity(self, entity, *, mode, etag, match_condition):
        from azure.core import MatchConditions
        from google.api_core.exceptions import FailedPrecondition, NotFound
        from google.cloud.firestore_v1 import LastUpdateOption

        if str(mode).lower() != "merge" or match_condition != MatchConditions.IfNotModified or etag is None:
            raise ValueError("Conditional merge requires the last-read entity version")
        row = dict(entity)
        pk, rk = row.get("PartitionKey"), row.get("RowKey")
        if pk is None or rk is None:
            raise ValueError("PartitionKey and RowKey are required")
        ref = self._collection.document(self._doc_id(pk, rk))
        try:
            ref.update(row, option=LastUpdateOption(etag))
        except (FailedPrecondition, NotFound) as exc:
            raise _StorageWriteConflict("Entity changed before conditional update") from exc

    def upsert_entity(self, entity, mode=None):
        row = dict(entity or {})
        pk, rk = row.get("PartitionKey"), row.get("RowKey")
        if pk is None or rk is None:
            raise ValueError("PartitionKey and RowKey are required")
        self._collection.document(self._doc_id(pk, rk)).set(
            row, merge=str(mode or "").lower() == "merge"
        )

    def create_entity(self, entity):
        from google.api_core.exceptions import AlreadyExists

        row = dict(entity or {})
        pk, rk = row.get("PartitionKey"), row.get("RowKey")
        if pk is None or rk is None:
            raise ValueError("PartitionKey and RowKey are required")
        ref = self._collection.document(self._doc_id(pk, rk))
        try:
            ref.create(row)
        except AlreadyExists as exc:
            raise _StorageWriteConflict("Entity was already created") from exc

    def delete_entity(self, *, partition_key, row_key):
        self._collection.document(self._doc_id(partition_key, row_key)).delete()

    def query_entities(self, query_filter=None):
        query = self._collection
        marker = "PartitionKey eq '"
        if query_filter and marker in str(query_filter):
            partition = str(query_filter).split(marker, 1)[1].split("'", 1)[0]
            try:
                query = query.where("PartitionKey", "==", partition)
            except TypeError:  # newer google-cloud-firestore prefers FieldFilter
                from google.cloud.firestore_v1.base_query import FieldFilter
                query = query.where(filter=FieldFilter("PartitionKey", "==", partition))
        return [dict(snap.to_dict() or {}) for snap in query.stream()]



def _storage_not_found(exc: Exception) -> bool:
    """Normalize Azure/Firestore missing-row semantics."""
    if isinstance(exc, KeyError):
        return True
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    name = exc.__class__.__name__.lower()
    return "resourcenotfound" in name or name in {"notfound", "notfounderror"}


def _storage_backend_policy() -> str:
    """Choose one durable admin backend; never silently split writes across stores."""
    configured = str(os.getenv("BLINQ_ADMIN_STORAGE_BACKEND") or "auto").strip().lower()
    if configured not in {"auto", "azure", "firestore"}:
        raise AdminStorageUnavailable("Invalid BLINQ_ADMIN_STORAGE_BACKEND")
    if configured == "auto":
        return "azure" if _connection_string() else "firestore"
    return configured


_AZURE_TABLE_CACHE: dict[tuple[str, str], object] = {}
_AZURE_TABLE_CACHE_LOCK = threading.Lock()

def _azure_table(name: str):
    """Return a provisioned Azure table client without provisioning on every read.

    Azure Functions reuses worker processes for many requests.  Creating/checking
    the table and performing a health read on every `_table()` call added network
    I/O to the hottest config/insight/account paths.  Cache only the SDK client;
    every real operation still performs its own storage request and surfaces
    transport/permission failures normally.
    """
    connection = _connection_string()
    if not connection:
        raise AdminStorageUnavailable("Azure admin storage is not configured")
    cache_key = (connection, str(name))
    cached = _AZURE_TABLE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        from azure.data.tables import TableServiceClient
        with _AZURE_TABLE_CACHE_LOCK:
            cached = _AZURE_TABLE_CACHE.get(cache_key)
            if cached is not None:
                return cached
            service = TableServiceClient.from_connection_string(connection)
            try:
                service.create_table_if_not_exists(table_name=name)
            except TypeError:  # SDK compatibility
                service.create_table_if_not_exists(name)
            client = service.get_table_client(name)
            # Validate the client once when it enters the process-local cache.
            pager = client.query_entities("PartitionKey eq '__blinq_health__'", results_per_page=1).by_page()
            try:
                next(iter(pager))
            except StopIteration:
                pass
            _AZURE_TABLE_CACHE[cache_key] = client
            return client
    except Exception as exc:
        raise AdminStorageUnavailable("Azure admin storage is unavailable") from exc

def _firestore_health() -> bool:
    try:
        adapter = _FirestoreTableAdapter("Health")
        # Force one read so a project without an enabled Firestore database is
        # not incorrectly reported as healthy just because the SDK initialized.
        adapter.query_entities(query_filter="PartitionKey eq '__blinq_health__'")
        return True
    except Exception:
        return False


def _azure_table_health() -> bool:
    connection = _connection_string()
    if not connection:
        return False
    try:
        from azure.data.tables import TableServiceClient
        service = TableServiceClient.from_connection_string(connection)
        try:
            service.create_table_if_not_exists("BlinQAdminHealth")
        except AttributeError:
            try:
                service.create_table("BlinQAdminHealth")
            except Exception:
                pass
        client = service.get_table_client("BlinQAdminHealth")
        # Materialize at most one page. An empty table is still a healthy store.
        list(client.query_entities("PartitionKey eq '__blinq_health__'", results_per_page=1).by_page())[:1]
        return True
    except Exception:
        return False


def admin_storage_diagnostics() -> dict:
    """Return safe admin-storage health using the same backend policy as reads/writes."""
    connection, connection_source = _connection_string_source()
    azure_configured = bool(connection)
    policy = "unavailable"
    try:
        policy = _storage_backend_policy()
    except AdminStorageUnavailable:
        pass
    azure_available = _azure_table_health() if policy == "azure" else False
    firestore_available = _firestore_health() if policy == "firestore" else False
    backend = policy if ((policy == "azure" and azure_available) or (policy == "firestore" and firestore_available)) else "unavailable"
    return {
        "backend": backend,
        "backend_policy": policy,
        "azure_configured": azure_configured,
        "azure_available": azure_available,
        "azure_connection_source": connection_source,
        "firestore_available": firestore_available,
        "requires_persistent_store": backend == "unavailable",
        "recommended_setting": "BLINQ_STORAGE_CONNECTION_STRING" if backend == "unavailable" and policy == "azure" else "",
        "services": {
            "premium_info": backend != "unavailable",
            "live_alert_history": backend != "unavailable",
            "admin_config": backend != "unavailable",
        },
    }


def admin_storage_backend() -> str:
    """Report which durable admin store is actually reachable in this runtime."""
    return str(admin_storage_diagnostics().get("backend") or "unavailable")


def _table(name: str):
    policy = _storage_backend_policy()
    if policy == "azure":
        return _azure_table(name)
    if policy == "firestore":
        return _FirestoreTableAdapter(name)
    raise AdminStorageUnavailable("Admin storage is unavailable")


def _encode_runtime_ui_payload(config: dict) -> str:
    """Encode UI config safely for Azure Table string-property limits.

    Azure Table stores strings as UTF-16. The current BlinQ UI config is large
    enough that a plain JSON string can exceed a single property limit even
    though its UTF-8 size still looks modest. Compressing the JSON keeps the
    entity small while remaining portable to the Firestore adapter.
    """
    raw = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = gzip.compress(raw, compresslevel=9, mtime=0)
    return "gzip:" + base64.b64encode(packed).decode("ascii")


def _decode_runtime_ui_payload(payload: object) -> dict | None:
    if not isinstance(payload, str) or not payload:
        return None
    try:
        if payload.startswith("gzip:"):
            packed = base64.b64decode(payload[5:].encode("ascii"), validate=True)
            raw = gzip.decompress(packed).decode("utf-8")
            parsed = json.loads(raw)
        else:
            # Backward compatibility with pre-r17 rows stored as plain JSON.
            parsed = json.loads(payload)
    except (ValueError, TypeError, UnicodeError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_membership_invariants(payload: object) -> object:
    """Heal legacy membership values before UI-config validation/serving.

    ROOKIE is a product invariant: always enabled, free and without a fixed
    expiry. Older Azure rows/browser drafts may still carry the former 30-day
    values, so rejecting those payloads would make Admin unable to publish the
    very migration that fixes them. GOAT is now finite and defaults to 365 days
    when a legacy lifetime row is encountered.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        schema = int(payload.get("schema") or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != 2:
        return payload
    plans = payload.get("plans")
    if isinstance(plans, dict):
        trial = plans.get("trial")
        if isinstance(trial, dict):
            trial["enabled"] = False
            trial["trial_hours"] = 0
            trial["duration_days"] = None
            trial["inherits"] = "rookie"

        rookie = plans.get("rookie")
        if isinstance(rookie, dict):
            rookie["enabled"] = True
            rookie["duration_days"] = None
            rookie["unlimited"] = True
            rookie["lifetime"] = False

        goat = plans.get("goat")
        if isinstance(goat, dict):
            goat["lifetime"] = False
            goat["unlimited"] = False
            days = goat.get("duration_days")
            if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
                goat["duration_days"] = 365

    # Access contract v1 aligns legacy runtime rows with the approved product
    # matrix once. After Admin republishes the migrated config, the marker
    # preserves future intentional changes instead of reapplying defaults.
    try:
        access_revision = int(payload.get("access_contract_revision") or 0)
    except (TypeError, ValueError):
        access_revision = 0
    if access_revision < 1:
        elements = payload.get("elements") or {}
        results_access = ((elements.get("SIDEBAR_RESULTS") or {}).get("access") or {})
        if isinstance(results_access, dict):
            results_access.update({
                "trial": "locked", "expired": "locked", "rookie": "locked",
                "pro": "locked", "elite": "locked", "legend": "active", "goat": "active",
            })

        dashboard = payload.get("dashboard") or {}
        tabs = ((dashboard.get("daily_hub") or {}).get("tabs") or {})

        def normalize_rule(tab_id, plan_id, visible_rows, *, selection="first", display="active", blur=True, see_all=False):
            rule = ((((tabs.get(tab_id) or {}).get("plans") or {}).get(plan_id)))
            if not isinstance(rule, dict):
                return
            rule.update({
                "visible_rows": visible_rows,
                "blur_remaining": bool(blur),
                "tab_enabled": display != "hidden",
                "see_all": bool(see_all),
                "selection_mode": selection,
                "display_state": display,
                "row_overrides": {},
            })

        for tab_id in ("daily", "prime", "value"):
            normalize_rule(tab_id, "rookie", 1, selection="stable_random")
            normalize_rule(tab_id, "pro", 3)
        for tab_id in ("ace", "double_faults", "doubles", "games", "sets"):
            normalize_rule(tab_id, "rookie", 0)
            normalize_rule(tab_id, "pro", 0)
        normalize_rule("see_all", "rookie", 0, display="blurred")
        normalize_rule("see_all", "pro", 0, display="blurred")
        for plan_id in ("elite", "legend", "goat"):
            for tab_id in ("daily", "prime", "value", "ace", "double_faults", "doubles", "games", "sets", "see_all"):
                normalize_rule(tab_id, plan_id, "ALL", blur=False, see_all=True)

        notifications = payload.setdefault("notifications", {})
        if isinstance(notifications, dict):
            notifications["live_min_level"] = "elite"
            notifications["default_min_level"] = "elite"
            notifications["default_levels"] = ["elite", "legend", "goat"]
        payload["access_contract_revision"] = 1

    # INFO contract v1 heals legacy runtime rows once so a code deploy is
    # sufficient to restore the one-way INFO channel for every active tier.
    # After this marker is present, Admin changes remain authoritative.
    try:
        info_revision = int(payload.get("info_contract_revision") or 0)
    except (TypeError, ValueError):
        info_revision = 0
    if info_revision < 1:
        notifications = payload.setdefault("notifications", {})
        if isinstance(notifications, dict):
            notifications.update({
                "enabled": True,
                "mode": "one_way",
                "one_way": True,
                "show_bell": True,
                "allow_user_replies": False,
                "read_tracking": True,
                "editable_levels": ["rookie", "pro", "elite", "legend", "goat"],
                "info_min_level": "rookie",
                "info_default_levels": ["rookie", "pro", "elite", "legend", "goat"],
            })
        payload["info_contract_revision"] = 1

    # Keep backend and frontend legacy migrations identical. Runtime rows may
    # intentionally be older than the current release, but missing access fields
    # must resolve to the same effective contract on both sides.
    patch_text = str(payload.get("ui_patch") or "")
    match = re.search(r"r(\d+)$", patch_text)
    patch_number = int(match.group(1)) if match else 0
    tabs = ((((payload.get("dashboard") or {}).get("daily_hub") or {}).get("tabs") or {}))
    if patch_number < 27:
        prime = tabs.get("prime")
        if isinstance(prime, dict):
            prime["enabled"] = True
    if patch_number < 33:
        rookie_prime = ((((tabs.get("prime") or {}).get("plans") or {}).get("rookie")))
        if isinstance(rookie_prime, dict):
            rookie_prime["selection_mode"] = "stable_random"

    inactivity = payload.get("account_inactivity")
    if isinstance(inactivity, dict) and inactivity.get("auto_expire_rookie") is True:
        # A user-facing warning is a hard prerequisite for automated account
        # deactivation. Heal older Admin drafts/runtime rows defensively.
        inactivity["notify_user"] = True
    return payload



_UI_ACCESS_DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "assets" / "ui_access_defaults.json"


def _deep_merge_dict(base: dict, override: dict) -> dict:
    result = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _release_access_defaults() -> dict:
    try:
        value = json.loads(_UI_ACCESS_DEFAULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise AdminStorageUnavailable("Release access defaults are unavailable") from exc
    if not isinstance(value, dict) or int(value.get("schema") or 0) != 2:
        raise AdminStorageUnavailable("Release access defaults are invalid")
    return value


def resolve_ui_access_config(runtime: dict | None) -> dict:
    """Return one server-owned effective entitlement config for FE and BE."""
    merged = _deep_merge_dict(_release_access_defaults(), runtime or {})
    normalized = _normalize_membership_invariants(merged)
    return normalized if isinstance(normalized, dict) else merged


def load_effective_ui_config() -> tuple[dict, bool, bool]:
    """Return (effective_config, runtime_configured, storage_available).

    Storage outages fall back to the committed release access contract instead
    of switching the server to a second set of hard-coded entitlement defaults.
    """
    try:
        runtime = load_runtime_ui_config()
        return resolve_ui_access_config(runtime), bool(runtime), True
    except AdminStorageUnavailable:
        return resolve_ui_access_config(None), False, False

def load_runtime_ui_config() -> dict | None:
    client = _table(UI_TABLE)
    try:
        entity = client.get_entity(partition_key="runtime", row_key="ui-config")
    except Exception as exc:
        # Missing config is normal; transport/auth/storage failures are not.
        if _storage_not_found(exc):
            return None
        raise AdminStorageUnavailable("Unable to load runtime UI configuration") from exc
    decoded = _decode_runtime_ui_payload(entity.get("payload"))
    return _normalize_membership_invariants(decoded) if decoded is not None else None



def save_live_worker_status(payload: object) -> dict:
    """Persist a tiny, non-secret heartbeat/snapshot for the autonomous LIVE worker."""
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    last_error = str(data.get("last_error") or "")[:160]
    scanned_at = str(data.get("scanned_at") or now)[:64]
    # `last_success_at` is the timestamp shown as "Last update" in the public
    # footer. A failed worker attempt must not masquerade as a successful LIVE
    # refresh. Successful snapshots advance it; error snapshots preserve the
    # last known success supplied by the worker error handler.
    last_success_at = str(data.get("last_success_at") or "")[:64]
    if not last_error:
        last_success_at = scanned_at
    safe = {
        "scanned_at": scanned_at,
        "last_success_at": last_success_at,
        "live_events": max(0, int(data.get("live_events") or 0)),
        "candidates": max(0, int(data.get("candidates") or 0)),
        "signals": max(0, int(data.get("signals") or 0)),
        "new_alerts": max(0, int(data.get("new_alerts") or 0)),
        "prime_total": max(0, int(data.get("prime_total") or 0)),
        "prime_eligible": max(0, int(data.get("prime_eligible") or 0)),
        "matched_prime_live": max(0, int(data.get("matched_prime_live") or 0)),
        "matched_eligible_live": max(0, int(data.get("matched_eligible_live") or 0)),
        "set2_candidates": max(0, int(data.get("set2_candidates") or 0)),
        "set2_priced": max(0, int(data.get("set2_priced") or 0)),
        "set2_eligible": max(0, int(data.get("set2_eligible") or 0)),
        "set2_push_thresholds": data.get("set2_push_thresholds") if isinstance(data.get("set2_push_thresholds"), dict) else {},
        "alert_storage_unavailable": bool(data.get("alert_storage_unavailable")),
        "alert_publish_error": str(data.get("alert_publish_error") or "")[:64],
        "heartbeat_persisted": True,
        "candidate_items": data.get("candidate_items") if isinstance(data.get("candidate_items"), list) else [],
        "signal_items": data.get("signal_items") if isinstance(data.get("signal_items"), list) else [],
        "thresholds": data.get("thresholds") if isinstance(data.get("thresholds"), dict) else {},
        "last_error": last_error,
        "budget_paused": bool(data.get("budget_paused")),
        "provider_skipped_reason": str(data.get("provider_skipped_reason") or "")[:64],
        "updated_at": now,
    }
    # Keep snapshots deliberately tiny; the durable insight table is the alert history.
    safe["candidate_items"] = safe["candidate_items"][:3]
    safe["signal_items"] = safe["signal_items"][:3]
    entity = {
        "PartitionKey": "runtime",
        "RowKey": "live-radar-worker-status",
        "payload": json.dumps(safe, ensure_ascii=False, separators=(",", ":")),
        "updated_at": now,
    }
    try:
        _table(UI_TABLE).upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save LIVE worker status") from exc
    return safe


def save_live_odds_peak(event_id: str, odds: float, *, observed_at: str = "", first_set: str = "") -> dict:
    """Persist the highest provider Match Winner price observed by LIVE Radar.

    This is display/research evidence only. It never changes the immutable
    publication odds, ROI, model selection or training data.
    """
    eid = str(event_id or "").strip()
    if not _VALID_ID.fullmatch(eid):
        raise ValueError("Invalid event ID")
    try:
        price = float(odds)
    except (TypeError, ValueError):
        raise ValueError("Invalid live odds") from None
    if not (1.0 < price < 100.0):
        raise ValueError("Invalid live odds")
    now = datetime.now(timezone.utc).isoformat()
    seen_at = str(observed_at or now)[:64]
    row_key = f"live-odds-peak:{eid}"
    client = _table(UI_TABLE)
    previous = {}
    try:
        previous = client.get_entity(partition_key="runtime", row_key=row_key)
    except Exception as exc:
        if not _storage_not_found(exc):
            raise AdminStorageUnavailable("Unable to load LIVE odds peak") from exc
    try:
        old_max = float(previous.get("max_live_odds") or 0.0)
    except (TypeError, ValueError):
        old_max = 0.0
    is_new_max = price > old_max + 1e-12
    payload = {
        "PartitionKey": "runtime",
        "RowKey": row_key,
        "event_id": eid,
        "current_live_odds": price,
        "max_live_odds": price if is_new_max else old_max,
        "max_live_odds_at": seen_at if is_new_max else str(previous.get("max_live_odds_at") or seen_at)[:64],
        "first_seen_at": str(previous.get("first_seen_at") or seen_at)[:64],
        "last_seen_at": seen_at,
        "observations": max(0, int(previous.get("observations") or 0)) + 1,
        "first_set": str(first_set or previous.get("first_set") or "")[:24],
        "scope": "comeback_after_first_set_loss",
        "provider_id": 1,
        "updated_at": now,
    }
    try:
        client.upsert_entity(payload, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save LIVE odds peak") from exc
    return {k: payload[k] for k in (
        "event_id", "current_live_odds", "max_live_odds", "max_live_odds_at",
        "first_seen_at", "last_seen_at", "observations", "first_set", "scope",
        "provider_id",
    )}


def load_live_odds_peak(event_id: str) -> dict | None:
    """Load one persisted LIVE odds peak by provider event ID."""
    eid = str(event_id or "").strip()
    if not _VALID_ID.fullmatch(eid):
        return None
    try:
        entity = _table(UI_TABLE).get_entity(
            partition_key="runtime", row_key=f"live-odds-peak:{eid}"
        )
    except Exception as exc:
        if _storage_not_found(exc):
            return None
        raise AdminStorageUnavailable("Unable to load LIVE odds peak") from exc
    out = {
        "event_id": str(entity.get("event_id") or eid),
        "current_live_odds": entity.get("current_live_odds"),
        "max_live_odds": entity.get("max_live_odds"),
        "max_live_odds_at": entity.get("max_live_odds_at"),
        "first_seen_at": entity.get("first_seen_at"),
        "last_seen_at": entity.get("last_seen_at"),
        "observations": entity.get("observations"),
        "first_set": entity.get("first_set"),
        "scope": entity.get("scope"),
        "provider_id": entity.get("provider_id"),
    }
    return out


def load_live_worker_status() -> dict | None:
    """Load the most recent autonomous LIVE worker heartbeat/snapshot."""
    try:
        entity = _table(UI_TABLE).get_entity(partition_key="runtime", row_key="live-radar-worker-status")
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = exc.__class__.__name__.lower()
        if status == 404 or "notfound" in name or isinstance(exc, KeyError):
            return None
        raise AdminStorageUnavailable("Unable to load LIVE worker status") from exc
    try:
        payload = json.loads(str(entity.get("payload") or "{}"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None

def save_match_status_snapshot(payload: object) -> dict:
    """Persist the compact hourly match-status map used by prediction tables."""
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    raw_statuses = data.get("statuses")
    raw_statuses = raw_statuses if isinstance(raw_statuses, dict) else {}
    statuses = {}
    for event_id, value in raw_statuses.items():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "").strip().lower()
        if status not in {"win", "loss", "retired", "void"}:
            continue
        eid = str(event_id or "").strip()[:64]
        if not eid:
            continue
        statuses[eid] = {
            "status": status,
            "checked_at": str(value.get("checked_at") or "")[:64],
            "winner_id": str(value.get("winner_id") or "")[:64],
            "provider_status": str(value.get("provider_status") or "")[:120],
        }
        # Only provider-confirmed settlement context is persisted. These fields
        # are display metadata, NEVER a replacement for immutable issued odds.
        first_outcome = str(value.get("first_set_outcome") or "").strip().lower()
        if first_outcome in {"win", "loss"}:
            statuses[eid]["first_set_outcome"] = first_outcome
        first_score = str(value.get("first_set_score") or "").strip()
        if re.fullmatch(r"(?:[0-7]):(?:[0-7])", first_score):
            statuses[eid]["first_set_score"] = first_score
        try:
            peak = float(value.get("max_live_odds"))
        except (TypeError, ValueError):
            peak = 0.0
        if 1.0 < peak < 100.0:
            statuses[eid]["max_live_odds"] = peak
            observed = str(value.get("max_live_odds_at") or "").strip()[:64]
            if observed:
                statuses[eid]["max_live_odds_at"] = observed
            statuses[eid]["live_odds_scope"] = "comeback_after_first_set_loss"
            try:
                observations = int(value.get("live_odds_observations") or 0)
            except (ValueError, TypeError, OverflowError):
                observations = 0
            statuses[eid]["live_odds_observations"] = max(0, min(100_000, observations))
    # Compact pending identities survive the next morning's feed rollover.
    raw_pending = data.get("pending")
    raw_pending = raw_pending if isinstance(raw_pending, dict) else {}
    pending = {}
    for eid, item in raw_pending.items():
        if not isinstance(item, dict):
            continue
        key = str(eid or "").strip()[:64]
        entry = {field: str(item.get(field) or "").strip()[:64]
                 for field in ("t", "s", "a", "b", "c", "p", "n")}
        if key and all(entry[field] for field in ("t", "s", "a", "b")):
            pending[key] = entry
    safe = {
        "schema": 1,
        "updated_at": str(data.get("updated_at") or now)[:64],
        "statuses": statuses,
        "pending": pending,
        "pending_count": len(pending),
        "tracked": max(0, int(data.get("tracked") or 0)),
        "due": max(0, int(data.get("due") or 0)),
        "window_candidates": max(0, int(data.get("window_candidates") or 0)),
        "window_min_age_minutes": max(0, int(data.get("window_min_age_minutes") or 0)),
        "window_max_age_minutes": max(0, int(data.get("window_max_age_minutes") or 0)),
        "priority_mode": bool(data.get("priority_mode", False)),
        "betting_day_start": str(data.get("betting_day_start") or "")[:64],
        "current_betting_day_due": max(0, int(data.get("current_betting_day_due") or 0)),
        "backlog_due": max(0, int(data.get("backlog_due") or 0)),
        "runtime_limited": bool(data.get("runtime_limited", False)),
        "checked": max(0, int(data.get("checked") or 0)),
        "skipped_live": max(0, int(data.get("skipped_live") or 0)),
        "provider_requests": max(0, int(data.get("provider_requests") or 0)),
        "budget_paused": bool(data.get("budget_paused", False)),
        "time_budget_exhausted": bool(data.get("time_budget_exhausted", False)),
        "newly_resolved": max(0, int(data.get("newly_resolved") or 0)),
        "successful_history": max(0, int(data.get("successful_history") or 0)),
        "failed_history": max(0, int(data.get("failed_history") or 0)),
        "matched_events": max(0, int(data.get("matched_events") or 0)),
        "preferred_route": "near" if data.get("preferred_route") == "near" else "history",
        "near_attempts": max(0, int(data.get("near_attempts") or 0)),
        "daily_attempts": max(0, int(data.get("daily_attempts") or 0)),
        "daily_matches": max(0, int(data.get("daily_matches") or 0)),
        "daily_errors": {
            str(k)[:64]: max(0, int(v))
            for k, v in list((data.get("daily_errors") or {}).items())[:8]
            if isinstance(k, str) and k.replace("_", "").isalnum()
        },
        "unmatched": max(0, int(data.get("unmatched") or 0)),
        "next_due_id": str(data.get("next_due_id") or "")[:64],
        "provider_errors": {
            str(k)[:64]: max(0, int(v))
            for k, v in list((data.get("provider_errors") or {}).items())[:8]
            if isinstance(k, str) and k.replace("_", "").isalnum()
        },
        "degraded": bool(data.get("degraded")),
        "terminal": len(statuses),
    }
    payload_json = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    # Azure Table limits string properties to 64 KiB (UTF-16).  Most snapshots
    # fit in one row after gzip+base64.  A long-lived pending backlog can still
    # exceed that ceiling, so store the encoded snapshot transactionally in
    # versioned chunks rather than dropping unfinished matches.
    payload_text = (_encode_runtime_ui_payload(safe)
                    if len(payload_json.encode("utf-16-le")) > 40_000
                    else payload_json)
    table = _table(UI_TABLE)
    try:
        if len(payload_text.encode("utf-16-le")) <= 60_000:
            table.upsert_entity({
                "PartitionKey": "runtime",
                "RowKey": "match-status-worker",
                "payload": payload_text,
                "updated_at": now,
            }, mode="replace")
            current_prefix = ""
        else:
            encoded = _encode_runtime_ui_payload(safe)
            version = uuid.uuid4().hex[:16]
            # 24k characters are at most 48 KiB as UTF-16, leaving generous
            # headroom below Azure Table's per-string-property limit.
            chunk_size = 24_000
            chunks = [
                encoded[offset:offset + chunk_size]
                for offset in range(0, len(encoded), chunk_size)
            ]
            if not chunks:
                raise AdminStorageUnavailable("Unable to encode match status snapshot")
            current_prefix = f"match-status-worker-chunk-{version}-"
            # Write all immutable versioned chunks first.  The manifest row is
            # replaced last, so readers either see the previous complete
            # snapshot or the new complete snapshot, never a partial write.
            for index, chunk in enumerate(chunks):
                table.upsert_entity({
                    "PartitionKey": "runtime",
                    "RowKey": f"{current_prefix}{index:04d}",
                    "version": version,
                    "chunk_index": index,
                    "payload": chunk,
                    "updated_at": now,
                }, mode="replace")
            manifest = {
                "__match_status_chunks__": 1,
                "version": version,
                "chunks": len(chunks),
                "updated_at": now,
            }
            table.upsert_entity({
                "PartitionKey": "runtime",
                "RowKey": "match-status-worker",
                "payload": json.dumps(manifest, separators=(",", ":")),
                "updated_at": now,
            }, mode="replace")
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save match status snapshot") from exc

    # Best-effort cleanup happens only after the authoritative manifest/single
    # row has been committed.  A cleanup failure cannot invalidate the snapshot.
    try:
        for row in table.query_entities("PartitionKey eq 'runtime'"):
            row_key = str(row.get("RowKey") or "")
            if not row_key.startswith("match-status-worker-chunk-"):
                continue
            if current_prefix and row_key.startswith(current_prefix):
                continue
            table.delete_entity(partition_key="runtime", row_key=row_key)
    except Exception:
        pass
    return safe


def load_match_status_snapshot() -> dict | None:
    """Load the last compact hourly match-status snapshot."""
    try:
        table = _table(UI_TABLE)
        entity = table.get_entity(
            partition_key="runtime", row_key="match-status-worker"
        )
    except Exception as exc:
        if _storage_not_found(exc):
            return None
        raise AdminStorageUnavailable("Unable to load match status snapshot") from exc

    payload = _decode_runtime_ui_payload(str(entity.get("payload") or "{}"))
    if not isinstance(payload, dict):
        return None
    if int(payload.get("__match_status_chunks__") or 0) != 1:
        # Accept both legacy JSON and gzip-encoded single-row snapshots.
        return payload

    version = str(payload.get("version") or "").strip()
    try:
        chunk_count = int(payload.get("chunks") or 0)
    except (TypeError, ValueError):
        chunk_count = 0
    if not re.fullmatch(r"[a-f0-9]{16}", version) or not (1 <= chunk_count <= 512):
        raise AdminStorageUnavailable("Invalid chunked match status manifest")

    prefix = f"match-status-worker-chunk-{version}-"
    parts: list[str] = []
    try:
        for index in range(chunk_count):
            row = table.get_entity(
                partition_key="runtime", row_key=f"{prefix}{index:04d}"
            )
            if str(row.get("version") or "") != version:
                raise AdminStorageUnavailable("Mismatched match status snapshot chunk")
            parts.append(str(row.get("payload") or ""))
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load match status snapshot chunks") from exc

    restored = _decode_runtime_ui_payload("".join(parts))
    if not isinstance(restored, dict):
        raise AdminStorageUnavailable("Invalid chunked match status snapshot")
    return restored


def save_account_worker_status(payload: object) -> dict:
    """Persist the last account-inactivity worker summary for Admin diagnostics."""
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    safe = {
        "scanned_at": str(data.get("scanned_at") or now)[:64],
        "scanned": max(0, int(data.get("scanned") or 0)),
        "inactive": max(0, int(data.get("inactive") or 0)),
        "warnings": max(0, int(data.get("warnings") or 0)),
        "expired": max(0, int(data.get("expired") or 0)),
        "subscription_7": max(0, int(data.get("subscription_7") or 0)),
        "subscription_3": max(0, int(data.get("subscription_3") or 0)),
        "user_emails": max(0, int(data.get("user_emails") or 0)),
        "mail_failures": max(0, int(data.get("mail_failures") or 0)),
        "admin_email": bool(data.get("admin_email", False)),
        "admin_emails": max(0, int(data.get("admin_emails") or 0)),
        "smtp_configured": bool(data.get("smtp_configured", False)),
        "enabled": bool(data.get("enabled", False)),
        "last_error": str(data.get("last_error") or "")[:160],
        "updated_at": now,
    }
    entity = {
        "PartitionKey": "runtime",
        "RowKey": "account-inactivity-worker-status",
        "payload": json.dumps(safe, ensure_ascii=False, separators=(",", ":")),
        "updated_at": now,
    }
    try:
        _table(UI_TABLE).upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save account worker status") from exc
    return safe


def load_account_worker_status() -> dict | None:
    try:
        entity = _table(UI_TABLE).get_entity(partition_key="runtime", row_key="account-inactivity-worker-status")
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = exc.__class__.__name__.lower()
        if status == 404 or "notfound" in name or isinstance(exc, KeyError):
            return None
        raise AdminStorageUnavailable("Unable to load account worker status") from exc
    try:
        payload = json.loads(str(entity.get("payload") or "{}"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None




def save_model_calibration_status(payload: object) -> dict:
    """Store only a small, validated, read-only model-monitor snapshot in Azure.

    Called exclusively by the secret-protected internal endpoint. No training,
    GitHub token, raw private ledger, player rows or model artifact is stored.
    """
    from .model_calibration_status import normalize_model_calibration_snapshot
    safe = normalize_model_calibration_snapshot(payload)
    now = datetime.now(timezone.utc).isoformat()
    safe["updated_at"] = now
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 24_000:
        raise ValueError("Calibration status exceeds safe Azure Table payload size")
    try:
        _table(UI_TABLE).upsert_entity({
            "PartitionKey": "runtime",
            "RowKey": "model-calibration-status-v1",
            "payload": encoded,
            "updated_at": now,
        }, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save calibration status") from exc
    return safe


def load_model_calibration_status() -> dict | None:
    from .model_calibration_status import with_freshness
    try:
        entity = _table(UI_TABLE).get_entity(
            partition_key="runtime", row_key="model-calibration-status-v1"
        )
    except Exception as exc:
        if _storage_not_found(exc):
            return None
        raise AdminStorageUnavailable("Unable to read calibration status") from exc
    try:
        payload = json.loads(str(entity.get("payload") or ""))
        return with_freshness(payload)
    except (ValueError, TypeError) as exc:
        raise AdminStorageUnavailable("Invalid persisted calibration status") from exc

def validate_ui_config(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid UI configuration")
    # r26: normalize product invariants BEFORE validation. This makes publishing
    # self-healing even when an old Azure row, stale browser tab or local Admin
    # draft still contains the former 30-day ROOKIE / lifetime GOAT values.
    _normalize_membership_invariants(payload)
    if int(payload.get("schema") or 0) != 2:
        raise ValueError("Unsupported UI configuration schema")
    # r25 intentionally accepts stale r22/r23 browser/Azure drafts and strips
    # retired membership gating from Hero banners before persistence. Keep the
    # historical in-place validation contract used by the admin storage tests.
    elements = payload.get("elements")
    plans = payload.get("plans")
    if not isinstance(elements, dict) or not isinstance(plans, dict):
        raise ValueError("UI configuration lacks plans/elements")

    required_plans = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}
    if not required_plans.issubset(plans):
        raise ValueError("UI configuration lacks required plans")
    plan_order = ["rookie", "pro", "elite", "legend", "goat"]
    if [plan for plan, _ in sorted(((plan, plans[plan].get("order")) for plan in plan_order), key=lambda item: int(item[1] or 99))] != plan_order:
        raise ValueError("Membership order must be Rookie, PRO, Elite, Legend, GOAT")
    # Product invariants have already been normalized above. Keep the explicit
    # checks as a defensive contract, but legacy values no longer block publish.
    if plans["rookie"].get("unlimited") is not True or plans["rookie"].get("duration_days") is not None or plans["rookie"].get("enabled") is not True:
        raise ValueError("ROOKIE normalization failed")
    goat = plans["goat"]
    for plan in ("pro", "elite", "legend", "goat"):
        days = plans[plan].get("duration_days")
        if not isinstance(days, int) or days <= 0:
            raise ValueError(f"{plan} requires a positive default duration")
    if not isinstance(plans["legend"].get("enabled"), bool):
        raise ValueError("Legend enabled flag must be boolean")
    for plan in plan_order:
        eyebrow = plans[plan].get("eyebrow", "")
        if not isinstance(eyebrow, str) or len(eyebrow) > 40:
            raise ValueError(f"{plan} membership eyebrow must be at most 40 characters")
    inactivity = payload.get("account_inactivity") or {}
    if not isinstance(inactivity, dict):
        raise ValueError("Account inactivity policy must be an object")
    for key in ("enabled", "notify_admin", "notify_user", "auto_expire_rookie"):
        if key in inactivity and not isinstance(inactivity.get(key), bool):
            raise ValueError(f"Account inactivity {key} must be boolean")
    inactive_days = inactivity.get("inactive_days", 30)
    warning_days = inactivity.get("warning_days", 7)
    if not isinstance(inactive_days, int) or not 14 <= inactive_days <= 3650:
        raise ValueError("Account inactivity threshold must be 14..3650 days")
    if not isinstance(warning_days, int) or not 1 <= warning_days < inactive_days:
        raise ValueError("Account inactivity warning must be between 1 day and the inactivity threshold")
    if any(plans[plan].get("hide_ads_allowed") is True for plan in plan_order):
        raise ValueError("Plan-based ad-free access is disabled")
    for plan in plan_order:
        if not _valid_destination(plans[plan].get("url"), allow_internal=False):
            raise ValueError(f"{plan} membership URL must use HTTPS")
    required_elements = {
        *(f"HERO_BANNER_{i}" for i in range(1, 6)),
        "PRIME_PICKS_PANEL", "TOP_DAILY_PANEL", "VALUE_PICKS_PANEL",
        "DOUBLES_PANEL", "ACE_PICKS_PANEL", "SG_PICKS_PANEL", "RESULTS_PANEL",
    }
    if not required_elements.issubset(elements):
        raise ValueError("UI configuration would change the fixed slot inventory")
    valid_states = {"active", "locked", "blurred", "hidden"}
    contexts = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}

    dashboard = payload.get("dashboard") or {}
    kpi_cards = dashboard.get("kpi_cards")
    # Existing saved Azure configs may not have this field yet. New changes
    # must be exactly three supported cards with individually valid periods.
    if kpi_cards is not None:
        if not isinstance(kpi_cards, list) or len(kpi_cards) != 3:
            raise ValueError("Dashboard setting requires exactly three cards")
        for index, card in enumerate(kpi_cards):
            if not isinstance(card, dict) or set(card) != {"metric", "period"}:
                raise ValueError(f"Invalid Dashboard setting card {index + 1}")
            metric, period = card["metric"], card["period"]
            if not isinstance(metric, str) or metric not in ALLOWED_PERIODS:
                raise ValueError(f"Invalid Dashboard setting metric {index + 1}")
            if not isinstance(period, str) or period not in ALLOWED_PERIODS[metric]:
                raise ValueError(f"Invalid Dashboard setting period {index + 1}")
    sections = dashboard.get("sections") or {}
    base_pick_section_order = ["prime", "top_daily", "value", "doubles", "ace", "sg"]
    pick_section_order = (["top200"] if isinstance(sections, dict) and "top200" in sections else []) + base_pick_section_order
    section_order = dashboard.get("section_order") or []
    legacy_section_set = {"prime", "top_daily", "value", "doubles", "ace", "sg", "results"}
    top200_section_set = legacy_section_set | {"top200"}
    if not isinstance(section_order, list) or set(section_order) not in (legacy_section_set, top200_section_set):
        raise ValueError("Dashboard section order must contain each configured public section exactly once")
    visible_slots = dashboard.get("visible_slots")
    if not isinstance(visible_slots, int) or not 1 <= visible_slots <= 6:
        raise ValueError("Dashboard visible_slots must be between 1 and 6")
    if dashboard.get("user_switches") is not False:
        raise ValueError("Dashboard section switches are admin-managed and must stay off for users")
    if dashboard.get("show_disabled_strip") is not False:
        raise ValueError("Public dashboard disabled-section strip must stay hidden")
    if not isinstance(dashboard.get("auto_replace_empty_sections"), bool):
        raise ValueError("Invalid dashboard empty-section replacement setting")
    for field, allowed in (("cards_per_panel_desktop", {1, 2, 3}), ("cards_per_panel_wide", {1, 2, 3, 4})):
        if dashboard.get(field) not in allowed:
            raise ValueError(f"Invalid dashboard card-density setting: {field}")
    detail = dashboard.get("match_detail") or {}
    detail_levels = ("rookie", "pro", "elite", "legend", "goat")
    if not isinstance(detail, dict):
        raise ValueError("Invalid match detail configuration")
    detail_plans = detail.get("plans") or {}
    for plan_id in ("trial", "expired", *detail_levels):
        if not isinstance(detail_plans.get(plan_id), bool):
            raise ValueError(f"Invalid match detail access for {plan_id}")
    detail_sections = detail.get("sections") or {}
    if not isinstance(detail_sections, dict) or set(detail_sections) != {"overview", "statistics", "radar", "history"}:
        raise ValueError("Invalid match detail section configuration")
    if detail_sections.get("overview") != "rookie":
        raise ValueError("Match detail overview must remain available from ROOKIE")
    for section_id in ("statistics", "radar", "history"):
        if str(detail_sections.get(section_id) or "").lower() not in detail_levels:
            raise ValueError(f"Invalid match detail minimum level for {section_id}")
    comparator = dashboard.get("comparator") or {}
    if not isinstance(comparator, dict):
        raise ValueError("Invalid comparator access configuration")
    comparator_plans = comparator.get("plans") or {}
    for plan_id in ("trial", "expired", *detail_levels):
        if not isinstance(comparator_plans.get(plan_id), bool):
            raise ValueError(f"Invalid comparator access for {plan_id}")
    results_windows = dashboard.get("results_history_window") or {}
    allowed_result_windows = {"24h", "48h", "3d", "7d", "14d", "30d", "all"}
    if not isinstance(results_windows, dict):
        raise ValueError("Invalid results history configuration")
    for plan_id in ("trial", "rookie", "pro", "elite", "legend", "goat"):
        if str(results_windows.get(plan_id) or "").lower() not in allowed_result_windows:
            raise ValueError(f"Invalid results history window for {plan_id}")
    daily_hub = dashboard.get("daily_hub") or {}
    if not isinstance(daily_hub, dict) or not isinstance(daily_hub.get("enabled"), bool):
        raise ValueError("Invalid Daily Picks hub configuration")
    if daily_hub.get("default_tab") not in {"daily", "top200", "prime", "top", "value", "ace", "double_faults", "games", "sets", "doubles", "board", "see_all"}:
        raise ValueError("Invalid Daily Picks default tab")
    for field in ("preview_rows", "expand_rows"):
        value = daily_hub.get(field)
        if not isinstance(value, int) or not 1 <= value <= 20:
            raise ValueError(f"Invalid Daily Picks setting: {field}")
    hub_tabs = daily_hub.get("tabs") or {}
    required_hub_tabs = {"daily", "value", "ace", "double_faults", "games", "sets"}
    allowed_hub_tabs = required_hub_tabs | {"top200", "prime", "top", "doubles", "board", "see_all"}
    if not isinstance(hub_tabs, dict) or not required_hub_tabs.issubset(hub_tabs) or not set(hub_tabs).issubset(allowed_hub_tabs):
        raise ValueError("Daily Picks hub must contain the core tabs and only supported consolidated tabs")
    for tab_id, tab in hub_tabs.items():
        if not isinstance(tab, dict) or not isinstance(tab.get("enabled"), bool):
            raise ValueError(f"Invalid Daily Picks tab: {tab_id}")
        plan_settings = tab.get("plans") or {}
        for plan_id in ("trial", "expired", "rookie", "pro", "elite", "legend", "goat"):
            rule = plan_settings.get(plan_id)
            if not isinstance(rule, dict):
                raise ValueError(f"Missing Daily Picks entitlement {tab_id}/{plan_id}")
            visible = rule.get("visible_rows")
            if not (visible == "ALL" or isinstance(visible, int) and 0 <= visible <= 10):
                raise ValueError(f"Invalid Daily Picks row count {tab_id}/{plan_id}")
            if not isinstance(rule.get("blur_remaining"), bool) or not isinstance(rule.get("tab_enabled"), bool) or not isinstance(rule.get("see_all", False), bool):
                raise ValueError(f"Invalid Daily Picks entitlement flags {tab_id}/{plan_id}")
            if str(rule.get("selection_mode") or "first") not in {"first", "stable_random"}:
                raise ValueError(f"Invalid Daily Picks selection mode {tab_id}/{plan_id}")
            if str(rule.get("display_state") or "active") not in {"active", "blurred", "hidden"}:
                raise ValueError(f"Invalid Daily Picks display state {tab_id}/{plan_id}")
            overrides = rule.get("row_overrides") or {}
            if not isinstance(overrides, dict):
                raise ValueError(f"Invalid Daily Picks row overrides {tab_id}/{plan_id}")
            for position, state in overrides.items():
                try:
                    index = int(position)
                except (TypeError, ValueError):
                    raise ValueError(f"Invalid Daily Picks row override position {tab_id}/{plan_id}")
                if not 1 <= index <= 10 or str(state) not in {"active", "blurred", "hidden"}:
                    raise ValueError(f"Invalid Daily Picks row override {tab_id}/{plan_id}/{position}")

    notifications = payload.get("notifications") or {}
    if notifications:
        live_min = str(notifications.get("live_min_level") or notifications.get("default_min_level") or "elite").lower()
        if live_min not in _INSIGHT_LEVELS:
            raise ValueError("Invalid LIVE minimum membership level")
        info_min = str(notifications.get("info_min_level") or "rookie").lower()
        if info_min not in _INSIGHT_LEVELS:
            raise ValueError("Invalid INFO minimum membership level")
        info_defaults = notifications.get("info_default_levels", list(_INSIGHT_LEVELS))
        if not isinstance(info_defaults, list) or not info_defaults or any(str(level).lower() not in _INSIGHT_LEVELS for level in info_defaults):
            raise ValueError("Invalid INFO default audience")

    required_dashboard_sections = {"prime", "top_daily", "value", "doubles", "ace", "sg", "results"}
    allowed_dashboard_sections = required_dashboard_sections | {"top200"}
    if (
        not isinstance(sections, dict)
        or not required_dashboard_sections.issubset(sections)
        or not set(sections).issubset(allowed_dashboard_sections)
    ):
        raise ValueError("Invalid dashboard section configuration")
    active_pick_windows = [key for key in pick_section_order if isinstance(sections.get(key), dict) and sections[key].get("dashboard_enabled") is True]
    expected_dashboard_orders = {}
    for section_id in sections:
        section = sections.get(section_id)
        if not isinstance(section, dict):
            raise ValueError(f"Invalid dashboard section: {section_id}")
        for flag in ("sidebar_enabled", "dashboard_enabled"):
            if not isinstance(section.get(flag), bool):
                raise ValueError(f"Invalid {flag} for {section_id}")
        order = section.get("dashboard_order")
        if not isinstance(order, int) or not 1 <= order <= 20:
            raise ValueError(f"Invalid dashboard order for {section_id}")
        preview = section.get("preview_limit")
        if not (preview == "ALL" or isinstance(preview, int) and 1 <= preview <= 20):
            raise ValueError(f"Invalid preview limit for {section_id}")
        plan_settings = section.get("plans") or {}
        if not isinstance(plan_settings, dict):
            raise ValueError(f"Invalid dashboard plan settings for {section_id}")
        for plan_id in ("trial", "expired", "rookie", "pro", "elite", "legend", "goat"):
            entitlement = plan_settings.get(plan_id)
            if not isinstance(entitlement, dict):
                raise ValueError(f"Missing dashboard entitlement {section_id}/{plan_id}")
            visible = entitlement.get("visible_picks")
            if not (visible == "ALL" or isinstance(visible, int) and 0 <= visible <= 10):
                raise ValueError(f"Invalid visible pick count for {section_id}/{plan_id}")
            if not isinstance(entitlement.get("blur_remaining"), bool) or not isinstance(entitlement.get("see_all"), bool):
                raise ValueError(f"Invalid dashboard entitlement flags for {section_id}/{plan_id}")
            plan_order = entitlement.get("order", order)
            if not isinstance(plan_order, int) or not 1 <= plan_order <= 20:
                raise ValueError(f"Invalid dashboard entitlement order for {section_id}/{plan_id}")

    ad_fallbacks = payload.get("ad_fallbacks") or {}
    allowed_priority = ["active_advertisement", "blinq_internal"]
    if ad_fallbacks.get("priority") not in (allowed_priority, ["active_advertisement", "rss_news", "blinq_internal"]):
        raise ValueError("Invalid ad fallback priority")

    advertisers = payload.get("advertisers") or {}
    campaigns = payload.get("campaigns") or {}
    if not isinstance(advertisers, dict) or not isinstance(campaigns, dict):
        raise ValueError("Invalid advertiser/campaign configuration")
    for advertiser_id, advertiser in advertisers.items():
        if not _VALID_ID.fullmatch(str(advertiser_id)) or not isinstance(advertiser, dict):
            raise ValueError("Invalid advertiser entry")
    for campaign_id, campaign in campaigns.items():
        if not _VALID_ID.fullmatch(str(campaign_id)) or not isinstance(campaign, dict):
            raise ValueError("Invalid campaign entry")
        advertiser_id = str(campaign.get("advertiser_id") or "")
        if advertiser_id and advertiser_id not in advertisers:
            raise ValueError(f"Campaign {campaign_id} references an unknown advertiser")
        creative_mode = str(campaign.get("creative_mode") or "full").lower()
        if creative_mode not in {"full", "split"}:
            raise ValueError(f"Campaign {campaign_id} has an invalid creative mode")
        image_fit = str(campaign.get("image_fit") or "cover").lower()
        image_position = str(campaign.get("image_position") or "center").lower()
        if image_fit not in {"cover", "contain"}:
            raise ValueError(f"Campaign {campaign_id} has an invalid image fit")
        if image_position not in {"center", "left", "right", "top", "bottom"}:
            raise ValueError(f"Campaign {campaign_id} has an invalid image position")
        images = campaign.get("images") or {}
        if not isinstance(images, dict) or any(str(key) not in {"1", "2", "3", "4"} for key in images):
            raise ValueError(f"Campaign {campaign_id} has an invalid creative inventory")
        for value in [campaign.get("image_url"), campaign.get("mobile_image_url"), *images.values()]:
            url = str(value or "").strip()
            if url and not _valid_destination(url, allow_internal=True):
                raise ValueError(f"Campaign {campaign_id} creative must use HTTPS or an absolute same-origin web path")

    rss = payload.get("rss") or {}
    if not isinstance(rss, dict):
        raise ValueError("Invalid RSS configuration")
    sources = rss.get("sources") or []
    if not isinstance(sources, list) or len(sources) > 8:
        raise ValueError("Invalid RSS source inventory")
    source_ids = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Invalid RSS source")
        source_id = str(source.get("id") or "").strip()
        if not source_id or not _VALID_ID.fullmatch(source_id) or source_id in source_ids:
            raise ValueError("Invalid or duplicate RSS source id")
        source_ids.add(source_id)
        url = str(source.get("url") or "").strip()
        if url and not _valid_destination(url, allow_internal=False):
            raise ValueError(f"RSS source {source_id} must use HTTPS")

    for element_id, element in elements.items():
        if not isinstance(element, dict):
            raise ValueError(f"Invalid UI element {element_id}")
        if element.get("kind") == "hero_banner":
            element.pop("access", None)
            element.pop("click_access", None)
        if element.get("kind") != "hero_banner":
            access = element.get("access")
            if not isinstance(access, dict) or not contexts.issubset(access):
                raise ValueError(f"UI element {element_id} lacks access rules")
            if any(str(access[key]).lower() not in valid_states for key in contexts):
                raise ValueError(f"UI element {element_id} has an invalid access state")
            if str(access.get("trial")).lower() != str(access.get("rookie")).lower():
                raise ValueError(f"UI element {element_id} trial access must inherit Rookie")
        content = element.get("content") or {}
        if isinstance(content, dict) and not _valid_destination(content.get("link"), allow_internal=True):
            raise ValueError(f"UI element {element_id} has an invalid destination URL")


    hero = payload.get("hero_banner") or {}
    if not isinstance(hero, dict) or not isinstance(hero.get("enabled", True), bool):
        raise ValueError("Invalid main banner configuration")
    hero_count = hero.get("slot_count", 0)
    if not isinstance(hero_count, int) or not 0 <= hero_count <= 5:
        raise ValueError("Invalid main banner slide count")
    rotation = hero.get("rotation_seconds", 10)
    if not isinstance(rotation, (int, float)) or not 3 <= float(rotation) <= 300:
        raise ValueError("Main banner rotation must be between 3 and 300 seconds")
    for flag in ("auto_rotate", "show_dots", "pause_on_hover"):
        if flag in hero and not isinstance(hero.get(flag), bool):
            raise ValueError(f"Invalid main banner flag: {flag}")
    detail_limit = dashboard.get("detail_pick_limit", 5)
    if not isinstance(detail_limit, int) or not 3 <= detail_limit <= 5:
        raise ValueError("Dashboard detail pick limit must be between 3 and 5")

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 128_000:
        raise ValueError("UI configuration is too large")
    return payload


def save_runtime_ui_config(payload: object, *, actor_id: str = "") -> dict:
    """Save published UI only after a durable snapshot of the previous version.

    Release JSON and source-code ZIPs cannot restore Azure-published banner
    images, links and text. Fail closed if snapshotting fails; never overwrite
    the sole prior published version without a recoverable copy.
    """
    config = validate_ui_config(payload)
    now = datetime.now(timezone.utc).isoformat()
    encoded = _encode_runtime_ui_payload(config)
    entity = {
        "PartitionKey": "runtime",
        "RowKey": "ui-config",
        "payload": encoded,
        "payload_encoding": "gzip+base64",
        "updated_at": now,
        "updated_by": str(actor_id or "")[:256],
    }
    client = _table(UI_TABLE)
    snapshot_id = None
    try:
        try:
            previous = client.get_entity(partition_key="runtime", row_key="ui-config")
        except Exception as exc:
            if not _storage_not_found(exc):
                raise
            previous = None
        if previous and _decode_runtime_ui_payload(previous.get("payload")) is not None:
            snapshot_id = "before-" + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%S%fZ"
            ) + "-" + uuid.uuid4().hex[:8]
            client.create_entity({
                "PartitionKey": UI_HISTORY_PARTITION,
                "RowKey": snapshot_id,
                "payload": previous["payload"],
                "payload_encoding": str(previous.get("payload_encoding") or ""),
                "previous_updated_at": str(previous.get("updated_at") or "")[:64],
                "previous_updated_by": str(previous.get("updated_by") or "")[:256],
                "saved_at": now,
                "saved_by": str(actor_id or "")[:256],
            })
        client.upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable(
            "Unable to snapshot previous UI configuration or save new configuration"
        ) from exc
    return {"saved": True, "updated_at": now, "previous_snapshot_id": snapshot_id}


def list_runtime_ui_snapshots(*, limit: int = 25) -> list[dict]:
    """Metadata only; accessible through the authenticated Admin endpoint."""
    client = _table(UI_TABLE)
    try:
        rows = client.query_entities(
            query_filter=f"PartitionKey eq '{UI_HISTORY_PARTITION}'"
        )
        items = [{
            "id": str(row.get("RowKey") or ""),
            "saved_at": str(row.get("saved_at") or ""),
            "previous_updated_at": str(row.get("previous_updated_at") or ""),
            "previous_updated_by": str(row.get("previous_updated_by") or ""),
        } for row in rows if _UI_SNAPSHOT_ID.fullmatch(str(row.get("RowKey") or ""))]
        return sorted(items, key=lambda row: row["id"], reverse=True)[:max(1, min(50, limit))]
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to list UI configuration snapshots") from exc


def load_runtime_ui_snapshot(snapshot_id: str) -> dict | None:
    """Read a past complete published config for explicit Admin preview."""
    if not _UI_SNAPSHOT_ID.fullmatch(str(snapshot_id or "")):
        raise ValueError("Invalid UI snapshot ID")
    client = _table(UI_TABLE)
    try:
        row = client.get_entity(
            partition_key=UI_HISTORY_PARTITION, row_key=snapshot_id
        )
    except Exception as exc:
        if _storage_not_found(exc):
            return None
        raise AdminStorageUnavailable("Unable to load UI configuration snapshot") from exc
    return _decode_runtime_ui_payload(row.get("payload"))


def _clean_id(value: object, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if not _VALID_ID.fullmatch(text):
        raise ValueError("Invalid analytics identifier")
    return text


def record_banner_event(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid analytics event")
    event_type = str(payload.get("event_type") or "").strip().lower()
    if event_type not in {"impression", "click"}:
        raise ValueError("Invalid analytics event type")
    slot_id = _clean_id(payload.get("slot_id"))
    if not slot_id:
        raise ValueError("Missing slot id")
    if not _VALID_BANNER_SLOT.fullmatch(slot_id):
        raise ValueError("Invalid banner slot")
    campaign_id = _clean_id(payload.get("campaign_id"), fallback=slot_id)
    advertiser_id = _clean_id(payload.get("advertiser_id"), fallback="unassigned")
    client_id = str(payload.get("client_id") or "")[:256]
    visitor_hash = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:24] if client_id else "anonymous"
    now = datetime.now(timezone.utc)
    entity = {
        "PartitionKey": now.strftime("%Y%m"),
        "RowKey": f"{int(now.timestamp()*1000):013d}-{uuid.uuid4().hex}",
        "event_type": event_type,
        "slot_id": slot_id,
        "campaign_id": campaign_id,
        "advertiser_id": advertiser_id,
        "visitor_hash": visitor_hash,
        "occurred_at": now.isoformat(),
    }
    client = _table(ANALYTICS_TABLE)
    try:
        client.create_entity(entity)
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to store banner analytics") from exc
    return {"accepted": True}


def _month_keys(start: datetime, end: datetime) -> list[str]:
    cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    keys = []
    while cursor <= end:
        keys.append(cursor.strftime("%Y%m"))
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
    return keys


def banner_analytics_summary(*, days: int = 30) -> dict:
    days = max(1, min(365, int(days)))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    client = _table(ANALYTICS_TABLE)
    campaigns: dict[str, dict] = {}
    overall_views = 0
    overall_clicks = 0
    overall_unique_views: set[str] = set()
    overall_unique_clicks: set[str] = set()

    for month in _month_keys(cutoff, now):
        try:
            rows = client.query_entities(query_filter=f"PartitionKey eq '{month}'")
        except Exception as exc:
            raise AdminStorageUnavailable("Unable to read banner analytics") from exc
        for row in rows:
            try:
                occurred = datetime.fromisoformat(str(row.get("occurred_at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=timezone.utc)
            if occurred < cutoff:
                continue
            campaign_id = str(row.get("campaign_id") or row.get("slot_id") or "unassigned")
            bucket = campaigns.setdefault(campaign_id, {
                "campaign_id": campaign_id,
                "advertiser_id": str(row.get("advertiser_id") or "unassigned"),
                "impressions": 0,
                "clicks": 0,
                "unique_impressions": set(),
                "unique_clicks": set(),
                "slots": defaultdict(int),
                "first_seen": occurred,
                "last_seen": occurred,
            })
            visitor = str(row.get("visitor_hash") or "anonymous")
            slot = str(row.get("slot_id") or "unknown")
            bucket["slots"][slot] += 1
            bucket["first_seen"] = min(bucket["first_seen"], occurred)
            bucket["last_seen"] = max(bucket["last_seen"], occurred)
            if row.get("event_type") == "click":
                bucket["clicks"] += 1
                bucket["unique_clicks"].add(visitor)
                overall_clicks += 1
                overall_unique_clicks.add(visitor)
            else:
                bucket["impressions"] += 1
                bucket["unique_impressions"].add(visitor)
                overall_views += 1
                overall_unique_views.add(visitor)

    serialized = []
    for bucket in campaigns.values():
        impressions = bucket["impressions"]
        serialized.append({
            "campaign_id": bucket["campaign_id"],
            "advertiser_id": bucket["advertiser_id"],
            "impressions": impressions,
            "unique_impressions": len(bucket["unique_impressions"]),
            "clicks": bucket["clicks"],
            "unique_clicks": len(bucket["unique_clicks"]),
            "ctr": (bucket["clicks"] / impressions) if impressions else 0.0,
            "slots": dict(sorted(bucket["slots"].items(), key=lambda item: (-item[1], item[0]))),
            "first_seen": bucket["first_seen"].isoformat(),
            "last_seen": bucket["last_seen"].isoformat(),
        })
    serialized.sort(key=lambda row: (-row["impressions"], row["campaign_id"]))
    return {
        "available": True,
        "days": days,
        "summary": {
            "impressions": overall_views,
            "unique_impressions": len(overall_unique_views),
            "clicks": overall_clicks,
            "unique_clicks": len(overall_unique_clicks),
            "ctr": (overall_clicks / overall_views) if overall_views else 0.0,
            "campaigns": len(serialized),
        },
        "campaigns": serialized,
    }


# --- BlinQ Insights / private member feed ---------------------------------
_INSIGHT_LEVELS = ("rookie", "pro", "elite", "legend", "goat")
_INSIGHT_TYPES = {"info", "insight", "alert", "live_watch", "set2", "vip"}

def membership_levels_from(min_level: str = "rookie") -> list[str]:
    level = str(min_level or "rookie").strip().lower()
    if level not in _INSIGHT_LEVELS:
        level = "rookie"
    return list(_INSIGHT_LEVELS[_INSIGHT_LEVELS.index(level):])

def live_min_level(config: dict | None = None) -> str:
    runtime = config if isinstance(config, dict) else None
    if runtime is None:
        runtime, _, _ = load_effective_ui_config()
    notifications = (runtime.get("notifications") or {}) if isinstance(runtime, dict) else {}
    level = str(notifications.get("live_min_level") or notifications.get("default_min_level") or "elite").strip().lower()
    return level if level in _INSIGHT_LEVELS else "elite"

def live_alert_levels(config: dict | None = None) -> list[str]:
    return membership_levels_from(live_min_level(config))


_LIVE_HISTORY_HOURS = {0, 24, 48, 72}


def live_history_rule(kind: str, config: dict | None = None) -> dict:
    """Resolve settled LIVE-history visibility without widening LIVE access."""
    kind = str(kind or "").strip().lower()
    if kind not in {"comeback", "set2"}:
        raise ValueError("Invalid LIVE history kind")
    runtime = config if isinstance(config, dict) else None
    if runtime is None:
        runtime, _, _ = load_effective_ui_config()
    notifications = (runtime.get("notifications") or {}) if isinstance(runtime, dict) else {}
    history = notifications.get("live_history") if isinstance(notifications, dict) else {}
    raw = history.get(kind) if isinstance(history, dict) else {}
    raw = raw if isinstance(raw, dict) else {}

    live_levels = live_alert_levels(runtime)
    if isinstance(raw.get("levels"), list):
        levels = []
        for value in raw["levels"]:
            level = str(value or "").strip().lower()
            if level in live_levels and level not in levels:
                levels.append(level)
    else:
        levels = list(live_levels)

    try:
        hours = int(raw.get("hours", 72))
    except (TypeError, ValueError):
        hours = 72
    if hours not in _LIVE_HISTORY_HOURS:
        hours = 72
    return {"levels": levels, "hours": hours}


def info_min_level(config: dict | None = None) -> str:
    runtime = config if isinstance(config, dict) else None
    if runtime is None:
        runtime, _, _ = load_effective_ui_config()
    notifications = (runtime.get("notifications") or {}) if isinstance(runtime, dict) else {}
    level = str(notifications.get("info_min_level") or "rookie").strip().lower()
    return level if level in _INSIGHT_LEVELS else "rookie"

def info_alert_levels(config: dict | None = None) -> list[str]:
    # INFO is audience-driven per message. The legacy info_min_level value is
    # retained only as the Admin composer default; it is not an authorization gate.
    return list(_INSIGHT_LEVELS)


_PROJECT_GROUP_COLORS = {"blue", "orange", "purple", "green", "teal", "pink", "gray"}
_PROJECT_PAYMENT_STATES = {"pending", "paid", "waived"}
_PROJECT_GROUP_ENTRY_MODES = {"open", "request", "locked"}


def _project_user_partition(user_id: object) -> str:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("Invalid project-group user id")
    return "user:" + hashlib.sha256(uid.encode("utf-8")).hexdigest()[:40]


def _project_member_row_key(user_id: object) -> str:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("Invalid project-group user id")
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:64]


def _project_deadline_iso(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid project group deadline") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _project_entry_mode(entity: dict) -> str:
    raw = str(entity.get("entry_mode") or "").strip().lower()
    if raw in _PROJECT_GROUP_ENTRY_MODES:
        return raw
    return "open" if bool(entity.get("self_join_enabled", True)) else "locked"


def _project_group_access(entity: dict, member_count: int, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    capacity = max(1, int(entity.get("capacity") or 1))
    mode = _project_entry_mode(entity)
    active = bool(entity.get("active", True))
    full = max(0, int(member_count or 0)) >= capacity
    deadline_text = str(entity.get("join_deadline") or "").strip()
    deadline_passed = False
    if deadline_text:
        try:
            deadline = datetime.fromisoformat(deadline_text.replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            deadline_passed = deadline.astimezone(timezone.utc) <= now
        except ValueError:
            deadline_passed = True
    locked = (not active) or mode == "locked" or full or deadline_passed
    reason = ""
    if not active:
        reason = "inactive"
    elif full:
        reason = "full"
    elif deadline_passed:
        reason = "deadline"
    elif mode == "locked":
        reason = "manual"
    return {
        "entry_mode": mode,
        "locked": locked,
        "lock_reason": reason,
        "full": full,
        "deadline_passed": deadline_passed,
        "can_join": active and not locked and mode == "open",
        "can_request": active and not locked and mode == "request",
    }


def normalize_project_group(payload: object, *, existing: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid project group")
    base = dict(existing or {})
    name = str(payload.get("name", base.get("name", "")) or "").strip()
    if not name or len(name) > 80:
        raise ValueError("Project group name must contain 1–80 characters")
    description = str(payload.get("description", base.get("description", "")) or "").strip()
    if len(description) > 1200:
        raise ValueError("Project group description is too long")
    color = str(payload.get("color", base.get("color", "blue")) or "blue").strip().lower()
    if color not in _PROJECT_GROUP_COLORS:
        raise ValueError("Invalid project group color")
    try:
        capacity = int(payload.get("capacity", base.get("capacity", 10)) or 10)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid project group capacity") from exc
    if capacity < 1 or capacity > 500:
        raise ValueError("Project group capacity must be between 1 and 500")
    try:
        total_cost_cents = int(payload.get("total_cost_cents", base.get("total_cost_cents", 0)) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid project group total cost") from exc
    if total_cost_cents < 0 or total_cost_cents > 100_000_000:
        raise ValueError("Project group total cost is out of range")
    currency = str(payload.get("currency", base.get("currency", "EUR")) or "EUR").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Invalid project group currency")
    payment_note = str(payload.get("payment_note", base.get("payment_note", "")) or "").strip()
    if len(payment_note) > 1200:
        raise ValueError("Project group payment note is too long")
    explicit_mode = payload.get("entry_mode", base.get("entry_mode"))
    if explicit_mode is None:
        entry_mode = "open" if bool(payload.get("self_join_enabled", base.get("self_join_enabled", True))) else "locked"
    else:
        entry_mode = str(explicit_mode or "").strip().lower()
    if entry_mode not in _PROJECT_GROUP_ENTRY_MODES:
        raise ValueError("Invalid project group entry mode")
    join_deadline = _project_deadline_iso(payload.get("join_deadline", base.get("join_deadline", "")))
    return {
        "name": name,
        "description": description,
        "color": color,
        "capacity": capacity,
        "total_cost_cents": total_cost_cents,
        "currency": currency,
        "payment_note": payment_note,
        "entry_mode": entry_mode,
        "join_deadline": join_deadline,
        # Legacy compatibility: self_join_enabled still means immediate self-join.
        "self_join_enabled": entry_mode == "open",
        "active": bool(payload.get("active", base.get("active", True))),
    }


def _project_group_from_entity(entity: dict, *, member_count: int = 0, joined: bool = False,
                               payment_status: str = "", request_status: str = "") -> dict:
    capacity = max(1, int(entity.get("capacity") or 1))
    total = max(0, int(entity.get("total_cost_cents") or 0))
    contribution = (total + capacity - 1) // capacity if total else 0
    access = _project_group_access(entity, member_count)
    return {
        "id": str(entity.get("RowKey") or ""),
        "name": str(entity.get("name") or ""),
        "description": str(entity.get("description") or ""),
        "color": str(entity.get("color") or "blue"),
        "capacity": capacity,
        "member_count": max(0, int(member_count or 0)),
        "spots_left": max(0, capacity - max(0, int(member_count or 0))),
        "total_cost_cents": total,
        "contribution_cents": contribution,
        "currency": str(entity.get("currency") or "EUR"),
        "payment_note": str(entity.get("payment_note") or ""),
        "entry_mode": access["entry_mode"],
        "effective_entry_mode": "locked" if access["locked"] else access["entry_mode"],
        "join_deadline": str(entity.get("join_deadline") or ""),
        "locked": bool(access["locked"]),
        "lock_reason": str(access["lock_reason"] or ""),
        "can_join": bool(access["can_join"]),
        "can_request": bool(access["can_request"]),
        "self_join_enabled": bool(access["can_join"]),
        "active": bool(entity.get("active", True)),
        "joined": bool(joined),
        "request_status": str(request_status or ""),
        "payment_status": str(payment_status or ""),
        "created_at": str(entity.get("created_at") or ""),
        "updated_at": str(entity.get("updated_at") or ""),
        "created_by": str(entity.get("created_by") or ""),
    }


def _project_group_entity(group_id: str) -> dict:
    group_id = str(group_id or "").strip()
    if not _VALID_ID.fullmatch(group_id):
        raise ValueError("Invalid project group id")
    try:
        return _table(PROJECT_GROUPS_TABLE).get_entity(partition_key="groups", row_key=group_id)
    except Exception as exc:
        if _is_missing_entity(exc):
            raise ValueError("Unknown project group") from exc
        raise AdminStorageUnavailable("Unable to load project group") from exc


def _project_group_rows(group_id: str) -> list[dict]:
    try:
        return list(_table(PROJECT_GROUP_MEMBERS_TABLE).query_entities(
            query_filter=f"PartitionKey eq 'group:{group_id}'"
        ))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load project group members") from exc


def _project_group_members(group_id: str) -> list[dict]:
    return [row for row in _project_group_rows(group_id)
            if str(row.get("status") or "joined") == "joined"]


def project_group_ids_for_user(user_id: object) -> set[str]:
    uid = str(user_id or "").strip()
    if not uid:
        return set()
    try:
        rows = list(_table(PROJECT_GROUP_MEMBERS_TABLE).query_entities(
            query_filter=f"PartitionKey eq '{_project_user_partition(uid)}'"
        ))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load user project groups") from exc
    return {
        str(row.get("group_id") or row.get("RowKey") or "")
        for row in rows
        if str(row.get("status") or "joined") == "joined"
    }


def list_project_groups(*, user_id: str = "", include_inactive: bool = False,
                        include_members: bool = False) -> dict:
    try:
        rows = list(_table(PROJECT_GROUPS_TABLE).query_entities(query_filter="PartitionKey eq 'groups'"))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to list project groups") from exc
    joined_ids = project_group_ids_for_user(user_id) if user_id else set()
    items = []
    for entity in rows:
        if not include_inactive and not bool(entity.get("active", True)):
            continue
        group_id = str(entity.get("RowKey") or "")
        group_rows = _project_group_rows(group_id)
        members = [row for row in group_rows if str(row.get("status") or "joined") == "joined"]
        requests = [row for row in group_rows if str(row.get("status") or "") == "requested"]
        own = next((row for row in group_rows if str(row.get("user_id") or "") == str(user_id or "")), None)
        own_status = str((own or {}).get("status") or "")
        item = _project_group_from_entity(
            entity,
            member_count=len(members),
            joined=group_id in joined_ids,
            payment_status=str((own or {}).get("payment_status") or ""),
            request_status=own_status if own_status == "requested" else "",
        )
        item["request_count"] = len(requests)
        if include_members:
            item["members"] = [{
                "user_id": str(row.get("user_id") or ""),
                "joined_at": str(row.get("joined_at") or ""),
                "payment_status": str(row.get("payment_status") or "pending"),
            } for row in members]
            item["requests"] = [{
                "user_id": str(row.get("user_id") or ""),
                "requested_at": str(row.get("requested_at") or ""),
            } for row in requests]
        items.append(item)
    items.sort(key=lambda row: (not bool(row.get("active")), str(row.get("name") or "").lower()))
    return {"items": items}


def save_project_group(payload: object, *, actor_id: str = "", group_id: str = "") -> dict:
    client = _table(PROJECT_GROUPS_TABLE)
    existing_entity = None
    if group_id:
        existing_entity = _project_group_entity(group_id)
    existing = _project_group_from_entity(existing_entity) if existing_entity else None
    clean = normalize_project_group(payload, existing=existing)
    now = datetime.now(timezone.utc).isoformat()
    row_key = group_id or f"pg-{int(datetime.now(timezone.utc).timestamp()*1000):013d}-{uuid.uuid4().hex[:8]}"
    entity = {
        "PartitionKey": "groups",
        "RowKey": row_key,
        **clean,
        "created_at": (existing_entity or {}).get("created_at") or now,
        "updated_at": now,
        "created_by": (existing_entity or {}).get("created_by") or str(actor_id or "")[:256],
        "updated_by": str(actor_id or "")[:256],
    }
    try:
        client.upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save project group") from exc
    members = _project_group_members(row_key)
    return _project_group_from_entity(entity, member_count=len(members))


def delete_project_group(group_id: str) -> dict:
    entity = _project_group_entity(group_id)
    rows = _project_group_rows(group_id)
    member_table = _table(PROJECT_GROUP_MEMBERS_TABLE)
    try:
        for row in rows:
            uid = str(row.get("user_id") or "")
            member_table.delete_entity(partition_key=f"group:{group_id}", row_key=_project_member_row_key(uid))
            try:
                member_table.delete_entity(partition_key=_project_user_partition(uid), row_key=group_id)
            except Exception as exc:
                if not _is_missing_entity(exc):
                    raise
        _table(PROJECT_GROUPS_TABLE).delete_entity(partition_key="groups", row_key=group_id)
    except Exception as exc:
        if not _is_missing_entity(exc):
            raise AdminStorageUnavailable("Unable to delete project group") from exc
    return {"deleted": True, "id": str(entity.get("RowKey") or group_id)}


def join_project_group(group_id: str, user_id: object, *, admin: bool = False) -> dict:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("Invalid project-group user id")
    entity = _project_group_entity(group_id)
    if not bool(entity.get("active", True)):
        raise ValueError("Project group is not active")
    rows = _project_group_rows(group_id)
    members = [row for row in rows if str(row.get("status") or "joined") == "joined"]
    existing = next((row for row in rows if str(row.get("user_id") or "") == uid), None)
    existing_status = str((existing or {}).get("status") or "")
    if existing_status == "joined":
        return _project_group_from_entity(
            entity, member_count=len(members), joined=True,
            payment_status=str((existing or {}).get("payment_status") or "pending"),
        )
    if len(members) >= max(1, int(entity.get("capacity") or 1)):
        raise ValueError("Project group is full")

    access = _project_group_access(entity, len(members))
    if admin:
        new_status = "joined"
    else:
        if access["locked"]:
            reason = access["lock_reason"]
            if reason == "full":
                raise ValueError("Project group is full")
            if reason == "deadline":
                raise ValueError("Project group joining deadline has passed")
            raise ValueError("Project group is locked")
        if access["entry_mode"] == "open":
            new_status = "joined"
        elif access["entry_mode"] == "request":
            new_status = "requested"
        else:
            raise ValueError("Project group is locked")

    now = datetime.now(timezone.utc).isoformat()
    payment_status = str((existing or {}).get("payment_status") or "pending")
    row = {
        "PartitionKey": f"group:{group_id}",
        "RowKey": _project_member_row_key(uid),
        "group_id": group_id,
        "user_id": uid,
        "status": new_status,
        "payment_status": payment_status if payment_status in _PROJECT_PAYMENT_STATES else "pending",
        "requested_at": str((existing or {}).get("requested_at") or now) if new_status == "requested" else "",
        "joined_at": str((existing or {}).get("joined_at") or now) if new_status == "joined" else "",
        "updated_at": now,
    }
    reverse = {
        **row,
        "PartitionKey": _project_user_partition(uid),
        "RowKey": group_id,
    }
    try:
        table = _table(PROJECT_GROUP_MEMBERS_TABLE)
        table.upsert_entity(row, mode="replace")
        table.upsert_entity(reverse, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to update project group membership") from exc
    members_after = len(members) + (1 if new_status == "joined" else 0)
    return _project_group_from_entity(
        entity,
        member_count=members_after,
        joined=new_status == "joined",
        payment_status=row["payment_status"] if new_status == "joined" else "",
        request_status=new_status if new_status == "requested" else "",
    )


def leave_project_group(group_id: str, user_id: object) -> dict:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("Invalid project-group user id")
    table = _table(PROJECT_GROUP_MEMBERS_TABLE)
    try:
        table.delete_entity(partition_key=f"group:{group_id}", row_key=_project_member_row_key(uid))
    except Exception as exc:
        if not _is_missing_entity(exc):
            raise AdminStorageUnavailable("Unable to leave project group") from exc
    try:
        table.delete_entity(partition_key=_project_user_partition(uid), row_key=group_id)
    except Exception as exc:
        if not _is_missing_entity(exc):
            raise AdminStorageUnavailable("Unable to leave project group") from exc
    return {"left": True, "group_id": group_id}


def set_project_member_payment(group_id: str, user_id: object, status: str) -> dict:
    uid = str(user_id or "").strip()
    status = str(status or "").strip().lower()
    if status not in _PROJECT_PAYMENT_STATES:
        raise ValueError("Invalid project payment status")
    row_key = _project_member_row_key(uid)
    table = _table(PROJECT_GROUP_MEMBERS_TABLE)
    try:
        current = table.get_entity(partition_key=f"group:{group_id}", row_key=row_key)
    except Exception as exc:
        if _is_missing_entity(exc):
            raise ValueError("User is not in this project group") from exc
        raise AdminStorageUnavailable("Unable to load project member") from exc
    if str(current.get("status") or "") != "joined":
        raise ValueError("User is not an approved project member")
    current["payment_status"] = status
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    reverse = dict(current)
    reverse["PartitionKey"] = _project_user_partition(uid)
    reverse["RowKey"] = group_id
    try:
        table.upsert_entity(current, mode="replace")
        table.upsert_entity(reverse, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to update project payment state") from exc
    return {"group_id": group_id, "user_id": uid, "payment_status": status}


_INSIGHT_PRIORITIES = {"normal", "important", "critical"}


def _iso_or_blank(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid insight date/time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_insight(payload: object, *, existing: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid insight")
    base = dict(existing or {})
    title = str(payload.get("title", base.get("title", "")) or "").strip()
    body = str(payload.get("body", base.get("body", "")) or "").strip()
    if not title or len(title) > 140:
        raise ValueError("Insight title must contain 1–140 characters")
    if not body or len(body) > 4000:
        raise ValueError("Insight body must contain 1–4000 characters")
    insight_type = str(payload.get("type", base.get("type", "insight")) or "insight").strip().lower()
    priority = str(payload.get("priority", base.get("priority", "normal")) or "normal").strip().lower()
    if insight_type not in _INSIGHT_TYPES:
        raise ValueError("Invalid insight type")
    if priority not in _INSIGHT_PRIORITIES:
        raise ValueError("Invalid insight priority")
    audience_mode = str(payload.get("audience_mode", base.get("audience_mode", "levels")) or "levels").strip().lower()
    if audience_mode not in {"levels", "groups"}:
        raise ValueError("Invalid insight audience mode")
    raw_group_ids = payload.get("group_ids", base.get("group_ids", []))
    if not isinstance(raw_group_ids, list):
        raise ValueError("Insight group_ids must be a list")
    group_ids = []
    for raw in raw_group_ids:
        group_id = str(raw or "").strip()
        if not _VALID_ID.fullmatch(group_id):
            raise ValueError("Invalid insight project group")
        if group_id not in group_ids:
            group_ids.append(group_id)
    if audience_mode == "groups":
        if insight_type in {"alert", "live_watch", "set2"}:
            raise ValueError("Project groups currently support INFO messages only")
        if not group_ids:
            raise ValueError("Select at least one project group")
        for group_id in group_ids:
            _project_group_entity(group_id)
    default_levels = live_alert_levels() if insight_type in {"alert", "live_watch", "set2"} else info_alert_levels()
    raw_levels = payload.get("levels", base.get("levels", default_levels))
    if not isinstance(raw_levels, list):
        raise ValueError("Insight levels must be a list")
    levels = []
    for raw in raw_levels:
        level = str(raw or "").strip().lower()
        if level not in _INSIGHT_LEVELS:
            raise ValueError("Invalid insight level")
        if level not in levels:
            levels.append(level)
    if not levels:
        raise ValueError("Select at least one insight level")
    # INFO and LIVE each have an independent global minimum configured in
    # Admin → Info & LIVE. A message may narrow its audience, but it may never
    # widen access below the corresponding global minimum.
    if insight_type in {"alert", "live_watch", "set2"}:
        allowed_live = set(live_alert_levels())
        invalid_levels = [level for level in levels if level not in allowed_live]
        if invalid_levels:
            required = live_min_level().upper()
            raise ValueError(f"LIVE alerts are available from {required} level")
    else:
        allowed_info = set(info_alert_levels())
        invalid_levels = [level for level in levels if level not in allowed_info]
        if invalid_levels:
            required = info_min_level().upper()
            raise ValueError(f"INFO is available from {required} level")
    link = str(payload.get("link", base.get("link", "")) or "").strip()
    if link and not _valid_destination(link, allow_internal=True):
        raise ValueError("Insight link must use HTTPS or a same-origin path")
    link_label = str(payload.get("link_label", base.get("link_label", "")) or "").strip()[:80]
    match_id = str(payload.get("match_id", base.get("match_id", "")) or "").strip()
    if match_id and not _VALID_ID.fullmatch(match_id):
        raise ValueError("Invalid insight match id")
    active = bool(payload.get("active", base.get("active", True)))
    pinned = bool(payload.get("pinned", base.get("pinned", False)))
    active_from = _iso_or_blank(payload.get("active_from", base.get("active_from", "")))
    active_until = _iso_or_blank(payload.get("active_until", base.get("active_until", "")))
    if active_from and active_until and active_until <= active_from:
        raise ValueError("Insight active_until must be after active_from")
    return {
        "title": title,
        "body": body,
        "type": insight_type,
        "priority": priority,
        "audience_mode": audience_mode,
        "group_ids": group_ids,
        "levels": levels,
        "link": link,
        "link_label": link_label,
        "match_id": match_id,
        "active": active,
        "pinned": pinned,
        "active_from": active_from,
        "active_until": active_until,
    }


def _insight_from_entity(entity: dict) -> dict:
    levels = []
    group_ids = []
    try:
        levels = json.loads(entity.get("levels_json") or "[]")
    except (TypeError, ValueError):
        levels = []
    try:
        group_ids = json.loads(entity.get("group_ids_json") or "[]")
    except (TypeError, ValueError):
        group_ids = []
    return {
        "id": str(entity.get("RowKey") or ""),
        "title": str(entity.get("title") or ""),
        "body": str(entity.get("body") or ""),
        "type": str(entity.get("type") or "insight"),
        "priority": str(entity.get("priority") or "normal"),
        "audience_mode": str(entity.get("audience_mode") or "levels"),
        "group_ids": [str(v) for v in group_ids if _VALID_ID.fullmatch(str(v))],
        "levels": [str(v) for v in levels if str(v) in _INSIGHT_LEVELS],
        "link": str(entity.get("link") or ""),
        "link_label": str(entity.get("link_label") or ""),
        "match_id": str(entity.get("match_id") or ""),
        "active": bool(entity.get("active", True)),
        "pinned": bool(entity.get("pinned", False)),
        "active_from": str(entity.get("active_from") or ""),
        "active_until": str(entity.get("active_until") or ""),
        "created_at": str(entity.get("created_at") or ""),
        "updated_at": str(entity.get("updated_at") or ""),
        "created_by": str(entity.get("created_by") or ""),
        "read_count": int(entity.get("read_count") or 0),
    }


def save_insight(payload: object, *, actor_id: str = "", insight_id: str = "") -> dict:
    client = _table(INSIGHTS_TABLE)
    existing_entity = None
    if insight_id:
        if not _VALID_ID.fullmatch(insight_id):
            raise ValueError("Invalid insight id")
        try:
            existing_entity = client.get_entity(partition_key="insights", row_key=insight_id)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            missing = status == 404 or "notfound" in exc.__class__.__name__.lower() or isinstance(exc, KeyError)
            if missing:
                raise ValueError("Unknown insight") from exc
            raise AdminStorageUnavailable("Unable to load insight") from exc
    existing = _insight_from_entity(existing_entity) if existing_entity else None
    clean = normalize_insight(payload, existing=existing)
    now = datetime.now(timezone.utc).isoformat()
    row_key = insight_id or f"msg-{int(datetime.now(timezone.utc).timestamp()*1000):013d}-{uuid.uuid4().hex[:10]}"
    entity = {
        "PartitionKey": "insights",
        "RowKey": row_key,
        **{k: v for k, v in clean.items() if k not in {"levels", "group_ids"}},
        "levels_json": json.dumps(clean["levels"], separators=(",", ":")),
        "group_ids_json": json.dumps(clean["group_ids"], separators=(",", ":")),
        "created_at": (existing_entity or {}).get("created_at") or now,
        "updated_at": now,
        "created_by": (existing_entity or {}).get("created_by") or str(actor_id or "")[:256],
        "updated_by": str(actor_id or "")[:256],
        "read_count": int((existing_entity or {}).get("read_count") or 0),
    }
    try:
        client.upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save insight") from exc
    item = _insight_from_entity(entity)
    # Push is deliberately best-effort and only fires for a newly published
    # message. Durable INFO/LIVE storage remains the source of truth.
    if not insight_id and str(item.get("audience_mode") or "levels") != "groups":
        try:
            from .push_notifications import dispatch_insight_push
            dispatch_insight_push(item)
        except Exception:
            pass
    return item


def load_insight_by_id(insight_id: str) -> dict | None:
    """Load one durable insight by deterministic id."""
    insight_id = str(insight_id or "").strip()
    if not _VALID_ID.fullmatch(insight_id):
        return None
    if insight_id.startswith(_LIVE_AUTO_PREFIXES) and _live_deleted(insight_id, "insight"):
        return None
    try:
        entity = _table(INSIGHTS_TABLE).get_entity(partition_key="insights", row_key=insight_id)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__.lower()
        if status == 404 or "notfound" in name or isinstance(exc, KeyError):
            return None
        raise AdminStorageUnavailable("Unable to load insight") from exc
    return _insight_from_entity(entity)



# Autonomous scans use deterministic IDs. Tombstones prevent deleted rows from
# reappearing on the next scan/settlement; LIVE posts and results are independent.
_LIVE_AUTO_PREFIXES = ("live-watch-", "live-comeback-", "live-set2-")
_LIVE_DELETION_PARTITION = "live-deletions"


def _is_missing_entity(exc: Exception) -> bool:
    return (getattr(exc, "status_code", None) == 404
            or "notfound" in type(exc).__name__.lower()
            or isinstance(exc, KeyError))


def _live_deletion_key(record_id: str, kind: str) -> str:
    if not _VALID_ID.fullmatch(str(record_id or "")) or kind not in {"insight", "result"}:
        raise ValueError("Invalid LIVE record id")
    return f"{kind}:{record_id}"


def _live_deleted(record_id: str, kind: str) -> bool:
    try:
        _table(INSIGHTS_TABLE).get_entity(
            partition_key=_LIVE_DELETION_PARTITION,
            row_key=_live_deletion_key(record_id, kind),
        )
        return True
    except Exception as exc:
        if _is_missing_entity(exc):
            return False
        raise AdminStorageUnavailable("Unable to verify LIVE deletion") from exc


def _live_deletion_ids(kind: str) -> set[str]:
    try:
        rows = _table(INSIGHTS_TABLE).query_entities(
            query_filter=f"PartitionKey eq '{_LIVE_DELETION_PARTITION}'"
        )
        return {str(row.get("record_id") or "")
                for row in rows if row.get("kind") == kind}
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to read LIVE deletion history") from exc


def _store_live_deletion(record_id: str, kind: str, *, actor_id: str = "") -> None:
    try:
        _table(INSIGHTS_TABLE).upsert_entity({
            "PartitionKey": _LIVE_DELETION_PARTITION,
            "RowKey": _live_deletion_key(record_id, kind),
            "kind": kind, "record_id": record_id,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "deleted_by": str(actor_id or "admin")[:256],
        }, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to record LIVE deletion") from exc


def delete_live_radar_result(result_id: str, *, actor_id: str = "") -> dict:
    """Delete just the specified settled comeback or Set-2 result."""
    result_id = str(result_id or "").strip()
    if not _VALID_ID.fullmatch(result_id) or not result_id.startswith(
            ("live-result-comeback-", "live-result-set2-")):
        raise ValueError("Invalid LIVE result id")
    client = _table(INSIGHTS_TABLE)
    try:
        existing = client.get_entity(partition_key="live-results", row_key=result_id)
    except Exception as exc:
        if _is_missing_entity(exc):
            return {"deleted": False, "id": result_id}
        raise AdminStorageUnavailable("Unable to load LIVE result") from exc
    if existing.get("kind") not in {"comeback", "set2"}:
        raise ValueError("Unsupported LIVE result")
    _store_live_deletion(result_id, "result", actor_id=actor_id)
    try:
        client.delete_entity(partition_key="live-results", row_key=result_id)
    except Exception as exc:
        if not _is_missing_entity(exc):
            raise AdminStorageUnavailable("Unable to delete LIVE result") from exc
    return {"deleted": True, "id": result_id, "kind": existing["kind"]}


def save_live_radar_result(payload: object, *, result_id: str) -> dict:
    """Persist one settled LIVE Radar signal result idempotently."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid LIVE result")
    result_id = str(result_id or "").strip()
    if not _VALID_ID.fullmatch(result_id):
        raise ValueError("Invalid LIVE result id")
    if _live_deleted(result_id, "result"):
        return {"id": result_id, "suppressed": True}
    kind = str(payload.get("kind") or "").strip().lower()
    outcome = str(payload.get("outcome") or "").strip().lower()
    if kind not in {"comeback", "set2"}:
        raise ValueError("Invalid LIVE result kind")
    if outcome not in {"win", "loss", "void"}:
        raise ValueError("Invalid LIVE result outcome")
    event_id = str(payload.get("event_id") or "").strip()[:64]
    if not event_id:
        raise ValueError("Missing LIVE result event")
    entity = {
        "PartitionKey": "live-results", "RowKey": result_id,
        "kind": kind, "outcome": outcome, "event_id": event_id,
        "reason": str(payload.get("reason") or "")[:40],
        "title": str(payload.get("title") or "")[:160],
        "source_id": str(payload.get("source_id") or "")[:96],
        "signal_at": str(payload.get("signal_at") or "")[:64],
        "settled_at": str(payload.get("settled_at") or datetime.now(timezone.utc).isoformat())[:64],
    }
    try:
        _table(INSIGHTS_TABLE).upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save LIVE result") from exc
    return {
        "id": result_id, "kind": kind, "outcome": outcome, "event_id": event_id,
        "title": entity["title"], "reason": entity["reason"], "source_id": entity["source_id"],
        "signal_at": entity["signal_at"], "settled_at": entity["settled_at"],
    }


def list_live_radar_results(
    *, limit: int = 60, plan: str = "", config: dict | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Newest settled confirmed comeback / Set-2 signals.

    Admin callers omit plan and receive the complete durable history. Member
    callers are filtered independently by kind, configured levels and the
    configured 0/24/48/72-hour history window.
    """
    try:
        rows = list(_table(INSIGHTS_TABLE).query_entities(query_filter="PartitionKey eq 'live-results'"))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to list LIVE results") from exc
    items = [{
        "id": str(row.get("RowKey") or ""),
        "kind": str(row.get("kind") or ""),
        "outcome": str(row.get("outcome") or ""),
        "reason": str(row.get("reason") or ""),
        "event_id": str(row.get("event_id") or ""),
        "title": str(row.get("title") or ""),
        "source_id": str(row.get("source_id") or ""),
        "signal_at": str(row.get("signal_at") or ""),
        "settled_at": str(row.get("settled_at") or ""),
    } for row in rows]
    deleted = _live_deletion_ids("result")
    items = [row for row in items if row["id"] not in deleted]

    member_plan = str(plan or "").strip().lower()
    if member_plan:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        filtered = []
        rule_cache = {}
        for row in items:
            kind = str(row.get("kind") or "").strip().lower()
            if kind not in {"comeback", "set2"}:
                continue
            if kind not in rule_cache:
                rule_cache[kind] = live_history_rule(kind, config)
            rule = rule_cache[kind]
            if member_plan not in rule["levels"] or rule["hours"] <= 0:
                continue
            try:
                settled = datetime.fromisoformat(
                    str(row.get("settled_at") or "").replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
            if settled.tzinfo is None:
                settled = settled.replace(tzinfo=timezone.utc)
            if settled.astimezone(timezone.utc) < current - timedelta(hours=rule["hours"]):
                continue
            filtered.append(row)
        items = filtered

    items.sort(key=lambda row: row.get("settled_at") or "", reverse=True)
    return items[:max(1, min(200, int(limit or 60)))]


_INFO_RESULT_PARTITION = "info-results"
_INFO_RESULT_OUTCOMES = {"win", "loss", "void"}


def _info_result_from_entity(entity: dict) -> dict:
    try:
        group_ids = json.loads(entity.get("group_ids_json") or "[]")
    except (TypeError, ValueError):
        group_ids = []
    return {
        "id": str(entity.get("RowKey") or ""),
        "source_id": str(entity.get("source_id") or ""),
        "outcome": str(entity.get("outcome") or ""),
        "audience_mode": str(entity.get("audience_mode") or "levels"),
        "group_ids": [str(v) for v in group_ids if _VALID_ID.fullmatch(str(v))],
        "title": str(entity.get("title") or ""),
        "body": str(entity.get("body") or ""),
        "match_id": str(entity.get("match_id") or ""),
        "published_at": str(entity.get("published_at") or ""),
        "settled_at": str(entity.get("settled_at") or ""),
        "settled_by": str(entity.get("settled_by") or ""),
    }


def save_info_result(insight_id: str, outcome: str, *, actor_id: str = "") -> dict:
    """Manually settle one INFO post as win/loss/void.

    Results are stored independently from the INFO row, so the evaluation
    history survives later message expiry or deletion and can be corrected by
    settling the same source again.
    """
    insight_id = str(insight_id or "").strip()
    outcome = str(outcome or "").strip().lower()
    if not _VALID_ID.fullmatch(insight_id):
        raise ValueError("Invalid insight id")
    if outcome not in _INFO_RESULT_OUTCOMES:
        raise ValueError("Invalid INFO result outcome")
    try:
        source = _table(INSIGHTS_TABLE).get_entity(
            partition_key="insights", row_key=insight_id
        )
    except Exception as exc:
        if _is_missing_entity(exc):
            raise ValueError("Unknown insight") from exc
        raise AdminStorageUnavailable("Unable to load INFO insight") from exc
    item = _insight_from_entity(source)
    if str(item.get("type") or "").lower() in {"alert", "live_watch", "set2"}:
        raise ValueError("LIVE insights use LIVE result settlement")
    now = datetime.now(timezone.utc).isoformat()
    result_id = f"info-result-{insight_id}"
    if len(result_id) > 96:
        result_id = f"info-result-{uuid.uuid5(uuid.NAMESPACE_URL, insight_id).hex}"
    entity = {
        "PartitionKey": _INFO_RESULT_PARTITION,
        "RowKey": result_id,
        "source_id": insight_id,
        "outcome": outcome,
        "title": str(item.get("title") or "")[:140],
        "body": str(item.get("body") or "")[:4000],
        "match_id": str(item.get("match_id") or "")[:96],
        "audience_mode": str(item.get("audience_mode") or "levels")[:16],
        "group_ids_json": json.dumps(item.get("group_ids") or [], separators=(",", ":")),
        "published_at": str(item.get("created_at") or "")[:64],
        "settled_at": now,
        "settled_by": str(actor_id or "")[:256],
    }
    try:
        _table(INSIGHTS_TABLE).upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save INFO result") from exc
    return _info_result_from_entity(entity)


def list_info_results(*, limit: int = 250) -> list[dict]:
    try:
        rows = list(_table(INSIGHTS_TABLE).query_entities(
            query_filter=f"PartitionKey eq '{_INFO_RESULT_PARTITION}'"
        ))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to list INFO results") from exc
    items = [_info_result_from_entity(row) for row in rows]
    items.sort(key=lambda row: row.get("settled_at") or "", reverse=True)
    return items[:max(1, min(500, int(limit or 250)))]


def delete_info_result(result_id: str, *, actor_id: str = "") -> dict:
    result_id = str(result_id or "").strip()
    if not _VALID_ID.fullmatch(result_id) or not result_id.startswith("info-result-"):
        raise ValueError("Invalid INFO result id")
    client = _table(INSIGHTS_TABLE)
    try:
        existing = client.get_entity(
            partition_key=_INFO_RESULT_PARTITION, row_key=result_id
        )
    except Exception as exc:
        if _is_missing_entity(exc):
            return {"deleted": False, "id": result_id}
        raise AdminStorageUnavailable("Unable to load INFO result") from exc
    try:
        client.delete_entity(
            partition_key=_INFO_RESULT_PARTITION, row_key=result_id
        )
    except Exception as exc:
        if not _is_missing_entity(exc):
            raise AdminStorageUnavailable("Unable to delete INFO result") from exc
    return {
        "deleted": True,
        "id": result_id,
        "source_id": str(existing.get("source_id") or ""),
        "deleted_by": str(actor_id or "")[:256],
    }

def save_automated_insight(payload: object, *, actor_id: str = "automation", insight_id: str) -> tuple[dict, bool]:
    """Create or refresh one deterministic system insight idempotently.

    LIVE automation uses stable IDs per event/stage. Repeated scans therefore
    refresh the body and short expiry window without emitting another push.
    Only the first durable create dispatches a browser push.
    """
    insight_id=str(insight_id or '').strip()
    if not _VALID_ID.fullmatch(insight_id): raise ValueError("Invalid automated insight id")
    if insight_id.startswith(_LIVE_AUTO_PREFIXES) and _live_deleted(insight_id, "insight"):
        return {"id": insight_id, "suppressed": True}, False
    client=_table(INSIGHTS_TABLE)
    try: existing_entity=client.get_entity(partition_key="insights",row_key=insight_id)
    except Exception as exc:
        status=getattr(exc,"status_code",None); name=exc.__class__.__name__.lower()
        if not (status==404 or "notfound" in name or isinstance(exc,KeyError)): raise AdminStorageUnavailable("Unable to load automated insight") from exc
    else:
        existing=_insight_from_entity(existing_entity)
        clean=normalize_insight(payload,existing=existing); now=datetime.now(timezone.utc).isoformat()
        entity={"PartitionKey":"insights","RowKey":insight_id,**{k:v for k,v in clean.items() if k not in {"levels","group_ids"}},"levels_json":json.dumps(clean["levels"],separators=(",",":")),"group_ids_json":json.dumps(clean["group_ids"],separators=(",",":")),"created_at":existing_entity.get("created_at") or now,"updated_at":now,"created_by":existing_entity.get("created_by") or str(actor_id or "automation")[:256],"updated_by":str(actor_id or "automation")[:256],"read_count":int(existing_entity.get("read_count") or 0)}
        try: client.upsert_entity(entity,mode="replace")
        except Exception as exc: raise AdminStorageUnavailable("Unable to refresh automated insight") from exc
        return _insight_from_entity(entity),False
    clean=normalize_insight(payload); now=datetime.now(timezone.utc).isoformat()
    entity={"PartitionKey":"insights","RowKey":insight_id,**{k:v for k,v in clean.items() if k not in {"levels","group_ids"}},"levels_json":json.dumps(clean["levels"],separators=(",",":")),"group_ids_json":json.dumps(clean["group_ids"],separators=(",",":")),"created_at":now,"updated_at":now,"created_by":str(actor_id or "automation")[:256],"updated_by":str(actor_id or "automation")[:256],"read_count":0}
    try: client.create_entity(entity)
    except Exception as exc:
        try:return _insight_from_entity(client.get_entity(partition_key="insights",row_key=insight_id)),False
        except Exception:raise AdminStorageUnavailable("Unable to create automated insight") from exc
    item=_insight_from_entity(entity)
    try:
        from .push_notifications import dispatch_insight_push
        dispatch_insight_push(item)
    except Exception:
        pass
    return item,True


def delete_insight(insight_id: str, *, actor_id: str = "") -> dict:
    insight_id = str(insight_id or "").strip()
    if not _VALID_ID.fullmatch(insight_id):
        raise ValueError("Invalid insight id")
    client = _table(INSIGHTS_TABLE)
    try:
        existing = client.get_entity(partition_key="insights", row_key=insight_id)
    except Exception as exc:
        if _is_missing_entity(exc):
            return {"deleted": False}
        raise AdminStorageUnavailable("Unable to load insight") from exc
    is_auto_live = (insight_id.startswith(_LIVE_AUTO_PREFIXES)
                    and str(existing.get("type") or "").lower()
                    in {"alert", "live_watch", "set2"})
    if is_auto_live:
        _store_live_deletion(insight_id, "insight", actor_id=actor_id)
    try:
        client.delete_entity(partition_key="insights", row_key=insight_id)
    except Exception as exc:
        if not _is_missing_entity(exc):
            raise AdminStorageUnavailable("Unable to delete insight") from exc
    return {"deleted": True, "suppressed": is_auto_live}


def list_insights(*, plan: str = "", user_id: str = "", include_inactive: bool = False, limit: int = 100) -> dict:
    plan = str(plan or "").strip().lower()
    now = datetime.now(timezone.utc)
    try:
        rows = list(_table(INSIGHTS_TABLE).query_entities(query_filter="PartitionKey eq 'insights'"))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to list insights") from exc
    read_ids: set[str] = set()
    if user_id:
        try:
            reads = _table(INSIGHT_READS_TABLE).query_entities(query_filter=f"PartitionKey eq 'user:{str(user_id)[:256]}'")
            read_ids = {str(row.get("RowKey") or "") for row in reads}
        except Exception as exc:
            raise AdminStorageUnavailable("Unable to load insight read state") from exc
    # Resolve runtime notification minima once per request, not once per insight.
    # With a large history this used to multiply UI-config storage reads by N.
    live_levels = set(live_alert_levels()) if plan and not include_inactive else set()
    info_levels = set(info_alert_levels()) if plan and not include_inactive else set()
    user_group_ids = project_group_ids_for_user(user_id) if user_id and not include_inactive else set()
    deleted_live = _live_deletion_ids("insight")
    items = []
    for entity in rows:
        item = _insight_from_entity(entity)
        if item["id"] in deleted_live:
            continue
        if not include_inactive:
            if not item["active"]:
                continue
            item_type = str(item.get("type") or "").lower()
            audience_mode = str(item.get("audience_mode") or "levels")
            if audience_mode == "groups":
                if not user_id or not user_group_ids.intersection(set(item.get("group_ids") or [])):
                    continue
            else:
                if plan and plan not in item["levels"]:
                    continue
                if plan and item_type in {"alert", "live_watch", "set2"} and plan not in live_levels:
                    continue
                if plan and item_type not in {"alert", "live_watch", "set2"} and plan not in info_levels:
                    continue
            try:
                starts = datetime.fromisoformat(item["active_from"]) if item["active_from"] else None
                ends = datetime.fromisoformat(item["active_until"]) if item["active_until"] else None
            except ValueError:
                continue
            if starts and starts > now:
                continue
            if ends and ends <= now:
                continue
        item["read"] = item["id"] in read_ids if user_id else False
        items.append(item)
    items.sort(key=lambda row: (not bool(row.get("pinned")), str(row.get("created_at") or "")), reverse=False)
    # Pinned first; within each group newest first.
    items = sorted(items, key=lambda row: str(row.get("created_at") or ""), reverse=True)
    items = sorted(items, key=lambda row: not bool(row.get("pinned")))
    items = items[:max(1, min(250, int(limit or 100)))]
    return {"items": items, "unread": sum(1 for row in items if not row.get("read"))}


def mark_insight_read(*, insight_id: str, user_id: str) -> dict:
    insight_id = str(insight_id or "").strip()
    user_id = str(user_id or "").strip()
    if not _VALID_ID.fullmatch(insight_id) or not user_id:
        raise ValueError("Invalid insight read marker")
    insights = _table(INSIGHTS_TABLE)
    reads = _table(INSIGHT_READS_TABLE)
    try:
        entity = insights.get_entity(partition_key="insights", row_key=insight_id)
    except Exception as exc:
        raise ValueError("Unknown insight") from exc
    read_entity = {
        "PartitionKey": f"user:{user_id[:256]}",
        "RowKey": insight_id,
        "read_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        reads.create_entity(read_entity)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        name = exc.__class__.__name__.lower()
        # Already read is idempotent. Firestore and Azure use different conflict types.
        if status != 409 and "alreadyexists" not in name and "resourceexists" not in name:
            raise AdminStorageUnavailable("Unable to save insight read state") from exc
        return {"read": True, "already_read": True}
    entity["read_count"] = int(entity.get("read_count") or 0) + 1
    entity["updated_at"] = entity.get("updated_at") or datetime.now(timezone.utc).isoformat()
    try:
        insights.upsert_entity(entity, mode="replace")
    except Exception:
        # Read state is authoritative; aggregate count is best effort.
        pass
    return {"read": True, "already_read": False}
