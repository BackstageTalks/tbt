"""Shift paid membership expiries when Admin changes a level's duration.

Owner rule (25.11.2026): changing e.g. LEGEND from 30 to 180 days adds the
difference (+150) to every active LEGEND account's current expiry, which equals
"original switch date + new duration". Shortening subtracts the difference but
never expires an account earlier than one day from now.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

PAID_PLANS = ("pro", "elite", "legend", "goat")


def plan_days(config: object) -> dict[str, int]:
    plans = (config or {}).get("plans") if isinstance(config, dict) else None
    out: dict[str, int] = {}
    for plan in PAID_PLANS:
        raw = (plans or {}).get(plan) if isinstance(plans, dict) else None
        days = raw.get("duration_days") if isinstance(raw, dict) else None
        if isinstance(days, int) and not isinstance(days, bool) and 0 < days <= 3650:
            out[plan] = days
    return out


def term_deltas(old: object, new: object) -> dict[str, int]:
    """Day differences for plans whose valid duration changed."""
    before, after = plan_days(old), plan_days(new)
    return {p: after[p] - before[p] for p in PAID_PLANS
            if p in before and p in after and after[p] != before[p]}


def shifted_expiry(expires_at: str, delta_days: int, now: datetime) -> str | None:
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if expiry.tzinfo is None:
        return None
    shifted = expiry + timedelta(days=delta_days)
    floor = now + timedelta(days=1)
    if delta_days < 0:
        # Never cut an account below tomorrow (unless it already ended sooner).
        shifted = max(shifted, min(expiry, floor))
    return shifted.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def apply_term_deltas(cfg, deltas: dict[str, int], *, actor_id: str = "",
                      now: datetime | None = None, list_users=None,
                      update_user_access=None, max_pages: int = 200) -> dict:
    """Shift every active account of a changed plan once. Never raises."""
    report = {"deltas": dict(deltas), "updated": 0, "skipped": 0, "errors": 0}
    if not deltas:
        return report
    if list_users is None or update_user_access is None:
        from .admin_accounts import list_users as _list, update_user_access as _update
        list_users = list_users or _list
        update_user_access = update_user_access or _update
    instant = now or datetime.now(timezone.utc)
    for page in range(1, max_pages + 1):
        try:
            users = list_users(cfg, page=page, per_page=200)
        except Exception:
            report["errors"] += 1
            break
        if not users:
            break
        for user in users:
            claims = user.get("app_metadata") or {}
            plan = str(claims.get("blinq_plan") or "").lower()
            if plan not in deltas or claims.get("blinq_status") != "active" \
                    or claims.get("role", "user") != "user":
                continue
            expires = claims.get("blinq_expires_at")
            new_expiry = shifted_expiry(expires, deltas[plan], instant) if expires else None
            if not new_expiry or new_expiry == expires:
                report["skipped"] += 1
                continue
            try:
                update_user_access(
                    cfg, user["id"],
                    {"role": "user", "plan": plan, "status": "active", "expires_at": new_expiry},
                    actor_id=actor_id,
                    expected_claims={"blinq_plan": claims.get("blinq_plan"),
                                     "blinq_expires_at": expires},
                )
                report["updated"] += 1
            except Exception:
                report["errors"] += 1
    return report
