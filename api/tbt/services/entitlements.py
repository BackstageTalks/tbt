"""Server-owned BlinQ membership entitlements.

This module is deliberately independent from the public UI configuration.  The
browser may decide how permitted data looks, but it must never decide which
premium rows a member is allowed to possess.
"""
from __future__ import annotations

from copy import deepcopy


SECTION_TO_FEED_KEY = {
    "prime": "prime_picks",
    "top_daily": "top_daily_picks",
    "value": "value_picks",
    "doubles": "doubles_picks",
    "ace": "ace_picks",
    "sg": "sg_picks",
}

# Keep this policy conservative and code-reviewed.  Runtime marketing/UI config
# must not be able to widen API authorization.
_POLICY = {
    "expired": {
        "prime": (1, False), "top_daily": (0, False), "value": (0, False),
        "doubles": (1, False), "ace": (0, False), "sg": (0, False),
    },
    "rookie": {
        "prime": (3, False), "top_daily": (2, False), "value": (1, False),
        "doubles": (1, False), "ace": (1, False), "sg": (1, False),
    },
    "pro": {
        "prime": (5, True), "top_daily": (5, True), "value": (3, True),
        "doubles": (3, True), "ace": (3, True), "sg": (3, True),
    },
    "elite": {key: ("ALL", True) for key in SECTION_TO_FEED_KEY},
    "legend": {key: ("ALL", True) for key in SECTION_TO_FEED_KEY},
    "goat": {key: ("ALL", True) for key in SECTION_TO_FEED_KEY},
    "admin": {key: ("ALL", True) for key in SECTION_TO_FEED_KEY},
}


def effective_plan(access: dict) -> str:
    """Map account access to a server authorization class."""
    if bool(access.get("is_admin")) or str(access.get("role") or "").lower() == "admin":
        return "admin"
    status = str(access.get("status") or "").lower()
    plan = str(access.get("plan") or "").lower()
    if status == "suspended":
        return "suspended"
    if status == "trial":
        return "rookie"
    if status in {"active", "lifetime"} and plan in {"rookie", "pro", "elite", "legend", "goat"}:
        return plan
    return "expired"


def entitlement_manifest(access: dict, payload: dict | None = None) -> dict:
    plan = effective_plan(access)
    if plan == "suspended":
        return {"plan": plan, "sections": {}, "results": False, "performance": False}
    policy = _POLICY.get(plan, _POLICY["expired"])
    sections = {}
    payload = payload or {}
    for section, feed_key in SECTION_TO_FEED_KEY.items():
        rows = payload.get(feed_key) if isinstance(payload.get(feed_key), list) else []
        limit, see_all = policy[section]
        returned = len(rows) if limit == "ALL" else min(len(rows), max(0, int(limit)))
        sections[section] = {
            "visible_picks": limit,
            "see_all": bool(see_all),
            "blur_remaining": limit != "ALL" and returned < len(rows),
            "total": len(rows),
            "returned": returned,
            "locked_count": max(0, len(rows) - returned),
        }
    return {
        "plan": plan,
        "sections": sections,
        # Results are intentionally public to authenticated, non-suspended members.
        "results": True,
        "performance": True,
    }


def filter_feed_for_access(payload: dict, access: dict) -> tuple[dict, dict]:
    """Return a copy containing only rows the account is allowed to possess."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid serving feed root")
    manifest = entitlement_manifest(access, payload)
    if manifest["plan"] == "suspended":
        raise PermissionError("account_suspended")

    result = deepcopy(payload)
    for section, feed_key in SECTION_TO_FEED_KEY.items():
        rows = payload.get(feed_key)
        if not isinstance(rows, list):
            continue
        limit = manifest["sections"][section]["visible_picks"]
        result[feed_key] = deepcopy(rows if limit == "ALL" else rows[: max(0, int(limit))])

    # `upcoming` can contain predictions outside the curated premium sections.
    # It is used for filters/metadata in the UI, but it can also leak model output.
    # Only top-tier/admin accounts receive it in full. Others receive a union of
    # event ids already permitted in curated sections, with sensitive fields removed.
    if manifest["plan"] not in {"elite", "legend", "goat", "admin"}:
        permitted_ids = {
            str(row.get("event_id") or "")
            for feed_key in SECTION_TO_FEED_KEY.values()
            for row in result.get(feed_key, [])
            if isinstance(row, dict)
        }
        safe_upcoming = []
        for row in payload.get("upcoming", []):
            if not isinstance(row, dict) or str(row.get("event_id") or "") not in permitted_ids:
                continue
            copy = deepcopy(row)
            # Remove model-selection/betting fields that may not be part of the
            # member's entitled curated pick payload.
            for key in ("winner_id", "signals", "quality", "betting", "model_version"):
                copy.pop(key, None)
            for player_key in ("player1", "player2"):
                player = copy.get(player_key)
                if isinstance(player, dict):
                    player.pop("probability", None)
            safe_upcoming.append(copy)
        result["upcoming"] = safe_upcoming

    return result, manifest
