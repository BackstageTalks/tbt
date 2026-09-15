"""Persistent admin UI configuration and banner analytics.

The store prefers Azure Table Storage and can fall back to Firebase Firestore.
Firebase Auth remains the runtime identity provider; tennis history stays outside the identity layer.
On Azure Functions, AzureWebJobsStorage is used automatically unless
BLINQ_ADMIN_STORAGE_CONNECTION_STRING is supplied.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import uuid
from urllib.parse import urlparse


class AdminStorageUnavailable(RuntimeError):
    pass


UI_TABLE = "BlinQAdminConfig"
ANALYTICS_TABLE = "BlinQBannerAnalytics"
INSIGHTS_TABLE = "BlinQInsights"
INSIGHT_READS_TABLE = "BlinQInsightReads"
_VALID_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_VALID_BANNER_SLOT = re.compile(r"^(?:HEADER_BANNER_[1-4]|HERO_BANNER_[1-5]|CONTENT_(?:TOP|MID|BOTTOM)_[1-4]|SIDEBAR_PROMO_[1-4]|VIP_RAIL)$")


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


def _connection_string() -> str:
    return str(
        os.getenv("BLINQ_ADMIN_STORAGE_CONNECTION_STRING")
        or os.getenv("AzureWebJobsStorage")
        or ""
    ).strip()


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
        return dict(snap.to_dict() or {})

    def upsert_entity(self, entity, mode=None):
        row = dict(entity or {})
        pk, rk = row.get("PartitionKey"), row.get("RowKey")
        if pk is None or rk is None:
            raise ValueError("PartitionKey and RowKey are required")
        self._collection.document(self._doc_id(pk, rk)).set(
            row, merge=str(mode or "").lower() == "merge"
        )

    def create_entity(self, entity):
        row = dict(entity or {})
        pk, rk = row.get("PartitionKey"), row.get("RowKey")
        if pk is None or rk is None:
            raise ValueError("PartitionKey and RowKey are required")
        ref = self._collection.document(self._doc_id(pk, rk))
        try:
            ref.create(row)
        except Exception as exc:
            # Audit row keys are UUID-backed, so a collision is exceptional.
            raise exc

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
    """Return safe admin-storage health without exposing connection details."""
    azure_configured = bool(_connection_string())
    azure_available = _azure_table_health() if azure_configured else False
    firestore_available = _firestore_health()
    backend = "azure_table" if azure_available else "firestore" if firestore_available else "unavailable"
    return {
        "backend": backend,
        "azure_configured": azure_configured,
        "azure_available": azure_available,
        "firestore_available": firestore_available,
        "requires_persistent_store": backend == "unavailable",
    }


def admin_storage_backend() -> str:
    """Report which durable admin store is actually reachable in this runtime."""
    return str(admin_storage_diagnostics().get("backend") or "unavailable")


def _table(name: str):
    connection = _connection_string()
    if not connection:
        return _FirestoreTableAdapter(name)
    try:
        from azure.data.tables import TableServiceClient
    except ImportError as exc:
        # Firebase is a valid fallback even if the optional Azure SDK is absent.
        try:
            return _FirestoreTableAdapter(name)
        except AdminStorageUnavailable:
            raise AdminStorageUnavailable("azure-data-tables is unavailable") from exc
    try:
        service = TableServiceClient.from_connection_string(connection)
        client = service.get_table_client(name)
        client.create_table()
        return client
    except Exception as exc:  # SDK-specific errors vary by transport/version.
        try:
            service = TableServiceClient.from_connection_string(connection)
            return service.get_table_client(name)
        except Exception:
            # If Azure storage credentials are broken during a deployment, keep
            # the admin usable via the same Firebase project instead of silently
            # losing all account controls.
            try:
                return _FirestoreTableAdapter(name)
            except AdminStorageUnavailable as inner:
                raise AdminStorageUnavailable("Admin storage is unavailable") from inner


def load_runtime_ui_config() -> dict | None:
    client = _table(UI_TABLE)
    try:
        entity = client.get_entity(partition_key="runtime", row_key="ui-config")
    except Exception as exc:
        # Missing config is normal; transport/auth/storage failures are not.
        status = getattr(exc, "status_code", None)
        name = exc.__class__.__name__.lower()
        if status == 404 or "resourcenotfound" in name or "resourcenotfounderror" in name:
            return None
        raise AdminStorageUnavailable("Unable to load runtime UI configuration") from exc
    payload = entity.get("payload")
    if not isinstance(payload, str):
        return None
    try:
        parsed = json.loads(payload)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_ui_config(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid UI configuration")
    if int(payload.get("schema") or 0) != 2:
        raise ValueError("Unsupported UI configuration schema")
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
    for plan in ("rookie", "pro", "elite", "legend"):
        days = plans[plan].get("duration_days")
        if not isinstance(days, int) or days <= 0:
            raise ValueError(f"{plan} requires a positive default duration")
    if not isinstance(plans["legend"].get("enabled"), bool):
        raise ValueError("Legend enabled flag must be boolean")
    if plans["goat"].get("lifetime") is not True or plans["goat"].get("duration_days") is not None:
        raise ValueError("GOAT must remain the lifetime top level")
    if any(plans[plan].get("hide_ads_allowed") is True for plan in plan_order):
        raise ValueError("Plan-based ad-free access is disabled")
    for plan in plan_order:
        if not _valid_destination(plans[plan].get("url"), allow_internal=False):
            raise ValueError(f"{plan} membership URL must use HTTPS")
    required_elements = {
        *(f"HEADER_BANNER_{i}" for i in range(1, 5)),
        *(f"HERO_BANNER_{i}" for i in range(1, 6)),
        *(f"CONTENT_TOP_{i}" for i in range(1, 5)),
        *(f"CONTENT_MID_{i}" for i in range(1, 5)),
        *(f"CONTENT_BOTTOM_{i}" for i in range(1, 5)),
        "SIDEBAR_PROMO_1", "SIDEBAR_PROMO_2", "SIDEBAR_PROMO_3", "SIDEBAR_PROMO_4",
        "PRIME_PICKS_PANEL", "TOP_DAILY_PANEL", "VALUE_PICKS_PANEL",
        "DOUBLES_PANEL", "ACE_PICKS_PANEL", "SG_PICKS_PANEL", "RESULTS_PANEL",
        "BTTS_BONUS_PANEL", "FOOTER_SYSTEM",
    }
    if not required_elements.issubset(elements):
        raise ValueError("UI configuration would change the fixed slot inventory")
    valid_states = {"active", "locked", "blurred", "hidden"}
    contexts = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}
    row_presets = {"1", "2", "3", "4", "1+1+1+1", "2+2", "2+1+1", "1+1+2"}
    content_rows = payload.get("content_rows") or {}
    for zone in ("content_top", "content_mid", "content_bottom"):
        row = content_rows.get(zone)
        if not isinstance(row, dict) or str(row.get("preset") or "") not in row_presets:
            raise ValueError(f"Invalid fixed row preset for {zone}")
        if "enabled" in row and not isinstance(row.get("enabled"), bool):
            raise ValueError(f"Invalid enabled flag for {zone}")
        slot_count = row.get("slot_count")
        if slot_count is not None and (not isinstance(slot_count, int) or not 0 <= slot_count <= 4):
            raise ValueError(f"Invalid slot count for {zone}")

    dashboard = payload.get("dashboard") or {}
    sections = dashboard.get("sections") or {}
    pick_section_order = ["prime", "top_daily", "value", "doubles", "ace", "sg"]
    section_order = dashboard.get("section_order") or []
    if not isinstance(section_order, list) or set(section_order) != {"prime", "top_daily", "value", "doubles", "ace", "sg", "results", "btts"}:
        raise ValueError("Dashboard section order must contain each public section exactly once")
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
    daily_hub = dashboard.get("daily_hub") or {}
    if not isinstance(daily_hub, dict) or not isinstance(daily_hub.get("enabled"), bool):
        raise ValueError("Invalid Daily Picks hub configuration")
    if daily_hub.get("default_tab") not in {"daily", "prime", "top", "value", "ace", "games", "doubles"}:
        raise ValueError("Invalid Daily Picks default tab")
    for field in ("preview_rows", "expand_rows"):
        value = daily_hub.get(field)
        if not isinstance(value, int) or not 1 <= value <= 20:
            raise ValueError(f"Invalid Daily Picks setting: {field}")
    hub_tabs = daily_hub.get("tabs") or {}
    required_hub_tabs = {"daily", "value", "ace", "games"}
    allowed_hub_tabs = required_hub_tabs | {"prime", "top", "doubles"}
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
            if not (visible == "ALL" or isinstance(visible, int) and 0 <= visible <= 20):
                raise ValueError(f"Invalid Daily Picks row count {tab_id}/{plan_id}")
            if not isinstance(rule.get("blur_remaining"), bool) or not isinstance(rule.get("tab_enabled"), bool) or not isinstance(rule.get("see_all", False), bool):
                raise ValueError(f"Invalid Daily Picks entitlement flags {tab_id}/{plan_id}")

    valid_dashboard_sections = {"prime", "top_daily", "value", "doubles", "ace", "sg", "results", "btts"}
    if not isinstance(sections, dict) or not valid_dashboard_sections.issubset(sections):
        raise ValueError("Invalid dashboard section configuration")
    active_pick_windows = [key for key in pick_section_order if isinstance(sections.get(key), dict) and sections[key].get("dashboard_enabled") is True]
    expected_dashboard_orders = {}
    for section_id in valid_dashboard_sections:
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
            if not (visible == "ALL" or isinstance(visible, int) and 0 <= visible <= 20):
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
        access = element.get("access")
        if not isinstance(access, dict) or not contexts.issubset(access):
            raise ValueError(f"UI element {element_id} lacks access rules")
        if any(str(access[key]).lower() not in valid_states for key in contexts):
            raise ValueError(f"UI element {element_id} has an invalid access state")
        if str(access.get("trial")).lower() != str(access.get("rookie")).lower():
            raise ValueError(f"UI element {element_id} trial access must inherit Rookie")
        click_access = element.get("click_access") or {}
        if click_access and (not isinstance(click_access, dict) or any(plan not in contexts or not isinstance(value, bool) for plan, value in click_access.items())):
            raise ValueError(f"Invalid click access for {element_id}")
        if click_access and "trial" in click_access and "rookie" in click_access and click_access["trial"] != click_access["rookie"]:
            raise ValueError(f"UI element {element_id} trial click access must inherit Rookie")
        content = element.get("content") or {}
        if isinstance(content, dict) and not _valid_destination(content.get("link"), allow_internal=True):
            raise ValueError(f"UI element {element_id} has an invalid destination URL")

    header_cta = payload.get("header_cta") or {}
    if not isinstance(header_cta, dict) or not isinstance(header_cta.get("enabled", True), bool):
        raise ValueError("Invalid header CTA configuration")
    header_count = header_cta.get("slot_count", 0)
    if not isinstance(header_count, int) or not 0 <= header_count <= 4:
        raise ValueError("Invalid header CTA slot count")

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
    config = validate_ui_config(payload)
    now = datetime.now(timezone.utc).isoformat()
    entity = {
        "PartitionKey": "runtime",
        "RowKey": "ui-config",
        "payload": json.dumps(config, ensure_ascii=False, separators=(",", ":")),
        "updated_at": now,
        "updated_by": str(actor_id or "")[:256],
    }
    client = _table(UI_TABLE)
    try:
        client.upsert_entity(entity, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save runtime UI configuration") from exc
    return {"saved": True, "updated_at": now}


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
_INSIGHT_TYPES = {"info", "insight", "alert", "vip"}
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
    raw_levels = payload.get("levels", base.get("levels", ["elite", "legend", "goat"]))
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
    try:
        levels = json.loads(entity.get("levels_json") or "[]")
    except (TypeError, ValueError):
        levels = []
    return {
        "id": str(entity.get("RowKey") or ""),
        "title": str(entity.get("title") or ""),
        "body": str(entity.get("body") or ""),
        "type": str(entity.get("type") or "insight"),
        "priority": str(entity.get("priority") or "normal"),
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
        **{k: v for k, v in clean.items() if k != "levels"},
        "levels_json": json.dumps(clean["levels"], separators=(",", ":")),
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
    return _insight_from_entity(entity)


def delete_insight(insight_id: str) -> dict:
    if not _VALID_ID.fullmatch(str(insight_id or "")):
        raise ValueError("Invalid insight id")
    client = _table(INSIGHTS_TABLE)
    try:
        client.delete_entity(partition_key="insights", row_key=insight_id)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status == 404 or "notfound" in exc.__class__.__name__.lower() or isinstance(exc, KeyError):
            return {"deleted": False}
        raise AdminStorageUnavailable("Unable to delete insight") from exc
    return {"deleted": True}


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
    items = []
    for entity in rows:
        item = _insight_from_entity(entity)
        if not include_inactive:
            if not item["active"] or (plan and plan not in item["levels"]):
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
