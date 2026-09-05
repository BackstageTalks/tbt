"""Small, authenticated serving snapshot. No database or ML dependency."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def empty_feed():
    return {"schema": 1, "generated_at": None, "model": None, "upcoming": [],
            "results": [], "performance": {}, "history": {}, "ready": False}


def read_feed(path):
    target = Path(path)
    if not target.is_file():
        return empty_feed()
    if target.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Serving feed exceeds the 10 MB cap")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != 1:
        raise ValueError("Unsupported serving schema")
    for key in ("upcoming", "results"):
        if not isinstance(payload.get(key), list):
            raise ValueError("Invalid serving feed")
    return payload


def visible_feed(payload, now=None):
    """Never present started matches or an old feed as fresh upcoming picks."""
    now = now or datetime.now(timezone.utc)
    result = dict(payload)
    result["upcoming"] = [row for row in payload.get("upcoming", [])
                          if datetime.fromisoformat(row["scheduled_at"]) > now]
    stamp = payload.get("generated_at")
    result["stale"] = not stamp or (now - datetime.fromisoformat(stamp)).total_seconds() > 12 * 3600
    return result
