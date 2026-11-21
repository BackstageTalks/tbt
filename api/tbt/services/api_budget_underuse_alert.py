"""Read-only 16:50 Bratislava check of unused shared TennisAPI budget.

Triggered by the existing externally scheduled match-status workflow. The API
does not reserve provider quota, call RapidAPI, change CDB or use native cron.
A durable create-only daily claim prevents duplicate or uncertain SMTP retries.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from azure.data.tables import UpdateMode

from ..providers.shared_budget import status as shared_budget_status
from .account_inactivity import admin_recipients
from .admin_storage import _table
from .auth_email import send_blinq_transactional_email, _smtp_ready

ZONE = ZoneInfo("Europe/Bratislava")
PROVIDER_PLAN_LIMIT = 15_000
SHARED_LIMIT = 14_500
THRESHOLD_PERCENT = 75
ALERT_BELOW = PROVIDER_PLAN_LIMIT * THRESHOLD_PERCENT // 100  # 11,250; strictly below
ALERT_TABLE = "BlinQApiUnderuseAlerts"
ALERT_PARTITION = "api-budget-underuse-v1"
START = time(16, 50)
END_EXCLUSIVE = time(17, 6)


class BudgetAlertUnavailable(RuntimeError):
    pass


def check_due(now: datetime, budget: dict | None) -> dict:
    """Pure, fail-closed eligibility. 16:50 target, grace until 17:05 local."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Alert time must be timezone-aware")
    local = now.astimezone(ZONE)
    if not START <= local.time().replace(tzinfo=None) < END_EXCLUSIVE:
        return {"status": "not_due", "betting_date": local.date().isoformat()}
    if not isinstance(budget, dict):
        raise BudgetAlertUnavailable("Shared API budget could not be verified")
    required = {
        "schema": 2, "provider_plan_limit": PROVIDER_PLAN_LIMIT,
        "global_limit": SHARED_LIMIT, "reserved_provider_headroom": 500,
        "window": "provider_day_17_09_utc",
    }
    if any(budget.get(k) != v for k, v in required.items()):
        raise BudgetAlertUnavailable("Unrecognized provider-day budget contract")
    spent, remaining = budget.get("global_spent"), budget.get("global_remaining")
    if (type(spent) is not int or type(remaining) is not int or
            not 0 <= spent <= SHARED_LIMIT or remaining != SHARED_LIMIT - spent):
        raise BudgetAlertUnavailable("Inconsistent shared API ledger")
    try:
        reset = datetime.fromisoformat(str(budget["next_reset_utc"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise BudgetAlertUnavailable("Provider reset not verified") from exc
    if (reset.tzinfo is None or not now < reset <= now + timedelta(hours=4) or
            reset.astimezone(timezone.utc).time() != time(17, 9) or
            reset.astimezone(ZONE).date() != local.date()):
        raise BudgetAlertUnavailable("Provider-day reset mismatch")
    info = {
        "betting_date": local.date().isoformat(),
        "global_spent": spent,
        "global_remaining": remaining,
        "provider_plan_limit": PROVIDER_PLAN_LIMIT,
        "threshold_requests": ALERT_BELOW,
        "percent": round(100 * spent / PROVIDER_PLAN_LIMIT, 2),
        "reset_local": reset.astimezone(ZONE).isoformat(),
    }
    return {"status": "notify" if spent < ALERT_BELOW else "threshold_met", **info}


def _conflict(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) in (409, 412)


def send_underuse_alert(cfg, *, now: datetime | None = None,
                        budget_reader=None, table=None, sender=None) -> dict:
    """No provider calls. At-most-once SMTP attempt per Bratislava date.

    Storage must succeed *before* SMTP. Unknown SMTP outcomes are deliberately
    not retried automatically; an operator can inspect the durable claim.
    """
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZONE)
    if not START <= local.time().replace(tzinfo=None) < END_EXCLUSIVE:
        return {"status": "not_due", "betting_date": local.date().isoformat()}
    reader = budget_reader or shared_budget_status
    try:
        decision = check_due(now, reader())
    except BudgetAlertUnavailable:
        raise
    except Exception as exc:
        raise BudgetAlertUnavailable("Authoritative shared budget is unavailable") from exc
    if decision["status"] != "notify":
        return decision

    recipients = admin_recipients(cfg)
    if not recipients or not _smtp_ready(cfg):
        raise BudgetAlertUnavailable("Admin recipients or SMTP are not configured")
    try:
        client = table if table is not None else _table(ALERT_TABLE)
        client.create_entity({
            "PartitionKey": ALERT_PARTITION, "RowKey": decision["betting_date"],
            "state": "claimed", "claimed_utc": now.astimezone(timezone.utc).isoformat(),
            "tracked_spent": decision["global_spent"],
            "recipient_count": len(recipients),
        })
    except Exception as exc:
        if _conflict(exc):
            return {**decision, "status": "already_claimed"}
        raise BudgetAlertUnavailable("Atomic daily mail claim unavailable") from exc

    accepted = 0
    failure = ""
    send = sender or send_blinq_transactional_email
    for recipient in recipients:
        try:
            ok = send(
                cfg, recipient,
                subject="BlinQ · RapidAPI pod 75 % o 16:50",
                eyebrow="BLINQ ADMIN · API",
                title_sk="Nevyužitý denný API rozpočet",
                body_sk=(
                    f"O 16:50 bolo v spoločnom BlinQ počítadle použitých "
                    f"{decision['global_spent']:,} z {PROVIDER_PLAN_LIMIT:,} požiadaviek "
                    f"({decision['percent']:.2f} %). To je menej než 75 % "
                    f"(11 250 požiadaviek). Do bezpečného stropu {SHARED_LIMIT:,} "
                    f"zostáva {decision['global_remaining']:,} požiadaviek. "
                    f"Reset poskytovateľa: {decision['reset_local']}. "
                    "Údaj vychádza zo spoločného BlinQ ledgeru, nie z nesledovaných "
                    "externých konzumentov. Táto kontrola nič nečerpá."
                ).replace(",", " "),
                title_en="Shared API budget under 75%",
                body_en=(
                    f"BlinQ tracked {decision['global_spent']} of 15000 calls "
                    f"({decision['percent']:.2f}%) at 16:50 Bratislava. "
                    f"{decision['global_remaining']} calls remain to the 14500 "
                    "shared safety ceiling. No provider requests were used by this check."
                ),
                button_label="Otvoriť BlinQ / Open BlinQ",
                button_url=(str(getattr(cfg, "blinq_public_url", "") or "").rstrip("/") +
                            "/#admin") if str(getattr(cfg, "blinq_public_url", "") or "").startswith("https://") else "",
            )
            if ok is True:
                accepted += 1
            else:
                failure = "smtp_not_accepted"
                break
        except Exception as exc:
            failure = exc.__class__.__name__
            break

    state = "smtp_accepted" if not failure and accepted == len(recipients) else "outcome_uncertain"
    try:
        client.upsert_entity({
            "PartitionKey": ALERT_PARTITION, "RowKey": decision["betting_date"],
            "state": state, "accepted_count": accepted, "failure_type": failure[:60],
        }, mode=UpdateMode.MERGE)
        persisted = client.get_entity(partition_key=ALERT_PARTITION,
                                      row_key=decision["betting_date"])
        if str(persisted.get("state")) != state or int(persisted.get("accepted_count", -1)) != accepted:
            raise BudgetAlertUnavailable("SMTP claim read-back inconsistent")
    except Exception as exc:
        raise BudgetAlertUnavailable("Mail outcome not durably verified; no auto retry") from exc
    if state != "smtp_accepted":
        raise BudgetAlertUnavailable("SMTP result uncertain or partially accepted; no auto retry")
    return {**decision, "status": "smtp_accepted", "accepted_count": accepted}
