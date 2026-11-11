"""Pure UTC provider-day ceiling for productive, bounded post-reset statistics.

The existing Azure CAS budget, provider header reserve, native writer lock,
and 5,000-request per-run cap remain authoritative. This policy only releases
part of the *already available* shared headroom after the 17:09 UTC reset,
leaving at least 6,000 calls below the 14,500 ceiling until daytime work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def evening_cap(now: datetime, next_reset: datetime) -> int | None:
    """Return a staged shared-spend ceiling for 00:45..06:00 after UTC reset."""
    if now.tzinfo is None or next_reset.tzinfo is None:
        raise ValueError("Provider-day timestamps must be timezone-aware")
    elapsed = (now.astimezone(timezone.utc) -
               (next_reset.astimezone(timezone.utc) - timedelta(days=1))).total_seconds()
    if 45 * 60 <= elapsed < 6 * 3600:
        return min(8500, 3000 + 1200 * int(elapsed // 3600))
    return None

SMOKE_SOURCE = "operator-approved-500-statistics-smoke"


def operator_smoke_request_cap(path, *, enabled: bool, now: datetime) -> int | None:
    """Apply a fresh operator's *restrictive* 500-call cap to one tick only.

    Only a non-dry-run, marker-approved push of the existing hourly tick can
    use this override. The existing shared CAS ledger, provider-header and
    writer checks remain authoritative.
    """
    if not enabled:
        return None

    import json
    from pathlib import Path

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("source") != SMOKE_SOURCE:
        return None
    if payload.get("schema") != 1 or type(payload.get("max_requests")) is not int or payload["max_requests"] != 500:
        raise ValueError("Invalid operator smoke request cap; no dispatch")

    requested = datetime.fromisoformat(str(payload.get("requested_utc", "")).replace("Z", "+00:00"))
    if requested.tzinfo is None or now.tzinfo is None:
        raise ValueError("Operator smoke request must use timezone-aware UTC")
    age = now.astimezone(timezone.utc) - requested.astimezone(timezone.utc)
    if not timedelta(0) <= age <= timedelta(minutes=25):
        raise ValueError("Operator smoke request expired or not yet valid; no dispatch")
    return 500


def external_clock_gapfill_decision(now: datetime, workflow_runs: list[dict]) -> tuple[bool, str, str]:
    """Attach the existing external match-status clock to the guarded gapfill.

    This function *only* decides whether to dispatch the existing orchestrator.
    The orchestrator itself rechecks the shared CAS quota, native CDB lock,
    provider-header reserve, UTC reset and per-run budget before any API use.
    """
    from zoneinfo import ZoneInfo

    if now.tzinfo is None:
        raise ValueError("External API scheduler requires timezone-aware UTC")
    now = now.astimezone(timezone.utc)
    reset = now.replace(hour=17, minute=9, second=0, microsecond=0)
    if now >= reset:
        reset += timedelta(days=1)
    until_reset = (reset - now).total_seconds()

    # Cold CDB bootstrap needs ~10-15 min: do not trigger an already doomed
    # provider run in the last 22 min before provider UTC reset.
    if until_reset <= 22 * 60:
        return False, "provider_cutoff_preflight", ""

    local = now.astimezone(ZoneInfo("Europe/Bratislava"))
    stage_hour = local.hour + (19 - reset.astimezone(ZoneInfo("Europe/Bratislava")).hour)
    final_topup = 7 * 60 <= until_reset <= 35 * 60 + 59
    permitted = (evening_cap(now, reset) is not None or
                 stage_hour in {12, 13, 14, 15, 16, 17, 18} or
                 final_topup)
    if not permitted:
        return False, "outside_existing_guarded_slots", ""

    # The final closeout window can release another 1,000 calls even if
    # the regular 16:00 UTC hourly staged allocation already dispatched.
    def slot(instant: datetime) -> str:
        remaining = (reset - instant).total_seconds()
        closeout = 7 * 60 <= remaining <= 35 * 60 + 59
        return instant.strftime("%Y-%m-%dT%H") + (
            ":closeout" if closeout else ":hourly"
        )

    target_slot = slot(now)
    recent = []
    for item in workflow_runs:
        if item.get("event") != "workflow_dispatch":
            continue
        raw = str(item.get("created_at") or "")
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("Ambiguous orchestrator run timestamp; fail closed")
        created = created.astimezone(timezone.utc)
        if created > now + timedelta(minutes=2):
            raise ValueError("Future orchestrator run timestamp; fail closed")
        if created < now - timedelta(hours=6):
            continue
        recent.append((created, item))

    # Never queue competing orchestrators while one is active or pending.
    if any(str(run.get("status")) in
           {"requested", "queued", "pending", "waiting", "in_progress"}
           for _, run in recent):
        return False, "orchestrator_already_active", target_slot

    for created, run in recent:
        if slot(created) != target_slot:
            continue
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            return False, "already_dispatched_this_slot", target_slot
        # Allow an automatic retry on the next existing 15-minute tick
        # after genuine guard failure, not duplicate runs immediately.
        if now - created < timedelta(minutes=12):
            return False, "retry_cooldown", target_slot

    return True, "eligible_external_clock_tick", target_slot
