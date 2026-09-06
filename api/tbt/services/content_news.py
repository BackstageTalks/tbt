"""Small trusted RSS aggregator for ad-free banner fallbacks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import json
import threading
import time
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx


CONFIG = Path(__file__).resolve().parents[2] / "config" / "content.json"
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {"expires": 0.0, "items": [], "signature": ""}


def _load_config() -> dict:
    try:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rss": {"enabled": False, "sources": []}}
    return payload if isinstance(payload, dict) else {"rss": {"enabled": False, "sources": []}}


def _safe_http_url(value: object) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _text(node, names):
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _published(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _entries(xml_bytes: bytes, source: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    source_name = str(source.get("name") or "Tennis news")[:80]
    priority = int(source.get("priority") or 0)
    rows = []
    # RSS 2.0 plus Atom. Namespace-agnostic matching keeps this dependency-free.
    nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"item", "entry"}]
    for node in nodes:
        title = _text(node, ["title", "{http://www.w3.org/2005/Atom}title"])
        link = _text(node, ["link"])
        if not link:
            for child in node:
                if child.tag.rsplit("}", 1)[-1] == "link":
                    link = str(child.attrib.get("href") or "").strip()
                    if link:
                        break
        link = _safe_http_url(link)
        if not title or not link:
            continue
        published_raw = _text(node, [
            "pubDate", "published", "updated",
            "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated",
        ])
        published = _published(published_raw)
        rows.append({
            "title": title[:240],
            "url": link,
            "source": source_name,
            "published_at": published.isoformat() if published else None,
            "priority": priority,
        })
    return rows


def news_pool(*, client=None, now=None, config=None) -> dict:
    now = now or datetime.now(timezone.utc)
    root = config if isinstance(config, dict) else _load_config()
    cfg = (root.get("rss") if isinstance(root, dict) else None) or {}
    if not cfg.get("enabled", True):
        return {"items": [], "sources": 0, "generated_at": now.isoformat()}
    sources = [row for row in (cfg.get("sources") or []) if isinstance(row, dict) and row.get("enabled", True)]
    sources = [row for row in sources if _safe_http_url(row.get("url"))]
    refresh_minutes = max(5, min(240, int(cfg.get("refresh_minutes") or 45)))
    max_age_hours = max(1, min(720, int(cfg.get("max_age_hours") or 48)))
    max_items = max(1, min(100, int(cfg.get("max_items") or 24)))

    signature = json.dumps(cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with _CACHE_LOCK:
        if _CACHE["expires"] > time.time() and _CACHE.get("signature") == signature:
            return {"items": list(_CACHE["items"]), "sources": len(sources), "generated_at": now.isoformat()}

    own = client is None
    client = client or httpx.Client(timeout=8, follow_redirects=True, headers={"User-Agent": "BlinQ-RSS/1.0"})
    collected = []
    try:
        for source in sources:
            try:
                response = client.get(_safe_http_url(source.get("url")))
                if response.status_code != 200 or len(response.content) > 2_000_000:
                    continue
                collected.extend(_entries(response.content, source))
            except httpx.HTTPError:
                continue
    finally:
        if own:
            client.close()

    cutoff = now - timedelta(hours=max_age_hours)
    seen_urls = set()
    seen_titles = set()
    usable = []
    for item in sorted(
        collected,
        key=lambda row: (
            -int(row.get("priority") or 0),
            str(row.get("published_at") or ""),
        ),
        reverse=False,
    ):
        published = _published(item.get("published_at") or "")
        if published and published < cutoff:
            continue
        url_key = item["url"].rstrip("/").lower()
        title_key = " ".join(item["title"].lower().split())
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        usable.append(item)
    # Re-sort after priority/date filtering: higher priority and newest first.
    usable.sort(key=lambda row: (
        int(row.get("priority") or 0),
        str(row.get("published_at") or ""),
    ), reverse=True)
    usable = usable[:max_items]
    with _CACHE_LOCK:
        _CACHE["items"] = list(usable)
        _CACHE["expires"] = time.time() + refresh_minutes * 60
        _CACHE["signature"] = signature
    return {"items": usable, "sources": len(sources), "generated_at": now.isoformat()}
