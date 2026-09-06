"""Persistent admin UI configuration and banner analytics.

The store uses Azure Table Storage, not Supabase. Supabase remains limited to
identity/account/profile metadata. On Azure Functions, AzureWebJobsStorage is
used automatically unless BLINQ_ADMIN_STORAGE_CONNECTION_STRING is supplied.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import uuid


class AdminStorageUnavailable(RuntimeError):
    pass


UI_TABLE = "BlinQAdminConfig"
ANALYTICS_TABLE = "BlinQBannerAnalytics"
_VALID_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")


def _connection_string() -> str:
    return str(
        os.getenv("BLINQ_ADMIN_STORAGE_CONNECTION_STRING")
        or os.getenv("AzureWebJobsStorage")
        or ""
    ).strip()


def _table(name: str):
    connection = _connection_string()
    if not connection:
        raise AdminStorageUnavailable("Admin storage is not configured")
    try:
        from azure.data.tables import TableServiceClient
    except ImportError as exc:
        raise AdminStorageUnavailable("azure-data-tables is unavailable") from exc
    try:
        service = TableServiceClient.from_connection_string(connection)
        client = service.get_table_client(name)
        client.create_table()
        return client
    except Exception as exc:  # SDK-specific errors vary by transport/version.
        # create_table raises when the table already exists; retry opening it.
        try:
            service = TableServiceClient.from_connection_string(connection)
            return service.get_table_client(name)
        except Exception as inner:
            raise AdminStorageUnavailable("Admin storage is unavailable") from inner


def load_runtime_ui_config() -> dict | None:
    client = _table(UI_TABLE)
    try:
        entity = client.get_entity(partition_key="runtime", row_key="ui-config")
    except Exception:
        return None
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
    required_elements = {
        *(f"HEADER_BANNER_{i}" for i in range(1, 4)),
        *(f"CONTENT_TOP_{i}" for i in range(1, 5)),
        *(f"CONTENT_BOTTOM_{i}" for i in range(1, 5)),
        "SIDEBAR_PROMO_1", "SIDEBAR_PROMO_2", "PRIME_PICKS_PANEL", "FOOTER_SYSTEM",
    }
    if not required_elements.issubset(elements):
        raise ValueError("UI configuration would change the fixed slot inventory")
    valid_states = {"active", "locked", "blurred", "hidden"}
    contexts = {"trial", "expired", "rookie", "pro", "elite", "goat", "legend"}
    row_presets = {"1+1+1+1", "2+2", "2+1+1", "1+1+2", "4"}
    content_rows = payload.get("content_rows") or {}
    for zone in ("content_top", "content_bottom"):
        row = content_rows.get(zone)
        if not isinstance(row, dict) or str(row.get("preset") or "") not in row_presets:
            raise ValueError(f"Invalid fixed row preset for {zone}")

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
        images = campaign.get("images") or {}
        if not isinstance(images, dict) or any(str(key) not in {"1", "2", "4"} for key in images):
            raise ValueError(f"Campaign {campaign_id} has an invalid creative inventory")
        for value in [campaign.get("image_url"), *images.values()]:
            url = str(value or "").strip()
            if url and not (url.startswith("https://") or url.startswith("http://") or url.startswith("/")):
                raise ValueError(f"Campaign {campaign_id} creative must be an HTTP(S) URL or an absolute web path")

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
        if url and not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError(f"RSS source {source_id} must use HTTP(S)")

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

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 48_000:
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
