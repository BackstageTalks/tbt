"""Daily BlinQ account lifecycle review.

The worker has two deliberately separate jobs:
1. FREE ROOKIE inactivity housekeeping: warn, then mark app access EXPIRED.
   It never disables or deletes the Firebase identity.
2. Paid membership reminders: one notice around 7 days and one around 3 days
   before the exact configured expiry timestamp.

All user notices use the canonical BlinQ transactional e-mail renderer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
import re
from zoneinfo import ZoneInfo

from .account_storage import (
    load_account_metadata,
    save_inactivity_state,
    save_subscription_notice_state,
)
from .admin_accounts import list_users, update_user_access
from .admin_storage import AdminStorageUnavailable
from .auth import account_access, firebase_get_user, is_admin
from .auth_email import send_blinq_transactional_email

_BRATISLAVA = ZoneInfo("Europe/Bratislava")
_EMAIL_SPLIT = re.compile(r"[;,\s]+")


def _parse_utc(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def inactivity_policy(runtime_config: object) -> dict:
    raw = runtime_config.get("account_inactivity") if isinstance(runtime_config, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    try:
        inactive_days = int(raw.get("inactive_days", 30))
    except (TypeError, ValueError):
        inactive_days = 30
    inactive_days = max(14, min(3650, inactive_days))
    try:
        warning_days = int(raw.get("warning_days", 7))
    except (TypeError, ValueError):
        warning_days = 7
    warning_days = max(1, min(inactive_days - 1, warning_days))
    # Historical field name retained for config compatibility. It now means
    # "mark inactive ROOKIE access EXPIRED"; Firebase identity is never disabled.
    expire_inactive = raw.get("auto_expire_rookie", True) is not False
    notify_user = raw.get("notify_user", True) is not False
    if expire_inactive:
        notify_user = True
    return {
        "enabled": raw.get("enabled", True) is not False,
        "inactive_days": inactive_days,
        "warning_days": warning_days,
        "notify_admin": raw.get("notify_admin", True) is not False,
        "notify_user": notify_user,
        "auto_expire_rookie": expire_inactive,
    }


def admin_recipients(cfg) -> list[str]:
    """Return de-duplicated admin recipients from plural + legacy env vars."""
    raw = " ".join([
        str(getattr(cfg, "blinq_admin_emails", "") or ""),
        str(getattr(cfg, "blinq_admin_email", "") or ""),
    ])
    result = []
    for item in _EMAIL_SPLIT.split(raw.strip()):
        email = item.strip().lower()
        if email and "@" in email and len(email) <= 320 and email not in result:
            result.append(email)
    return result[:20]


def smtp_diagnostics(cfg) -> dict:
    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    sender = str(getattr(cfg, "blinq_smtp_from", "") or "").strip()
    port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    recipients = admin_recipients(cfg)
    configured = bool(host and sender and 1 <= port <= 65535)
    return {
        "configured": configured,
        "admin_recipient_configured": bool(recipients),
        "admin_recipient_count": len(recipients),
        "host_configured": bool(host),
        "from_configured": bool(sender),
        "port": port,
        "starttls": bool(getattr(cfg, "blinq_smtp_starttls", True)),
    }


def _public_url(cfg) -> str:
    value = str(getattr(cfg, "blinq_public_url", "") or "").strip().rstrip("/")
    return value if value.startswith("https://") else ""


def _send_mail(cfg, recipient: str, subject: str, body: str) -> bool:
    """Compatibility wrapper used by older tests/admin reports."""
    return send_blinq_transactional_email(
        cfg,
        recipient,
        subject=subject,
        eyebrow="BLINQ ACCOUNT",
        title_sk=subject.replace("BlinQ · ", "", 1),
        body_sk=body,
        title_en="BlinQ account update",
        body_en="This is an automated BlinQ account notification. Please review the Slovak text above.",
        button_label="Otvoriť BlinQ / Open BlinQ" if _public_url(cfg) else "",
        button_url=_public_url(cfg),
    )


def _last_seen(user: dict, meta: dict | None = None):
    candidates = [
        _parse_utc((meta or {}).get("last_activity_at")),
        _parse_utc(user.get("last_sign_in_at")),
        _parse_utc(user.get("created_at")),
    ]
    return max((value for value in candidates if value), default=None)


def _marker_is_for_current_inactivity(marker, last_seen) -> bool:
    marked = _parse_utc(marker)
    return bool(marked and last_seen and marked >= last_seen)


def _format_expiry(value: datetime) -> tuple[str, str]:
    local = value.astimezone(_BRATISLAVA)
    sk = f"{local.day}. {local.month}. {local.year} o {local:%H:%M}"
    en = local.strftime("%d %b %Y at %H:%M") + " (Europe/Bratislava)"
    return sk, en


def _send_inactivity_warning(cfg, user: dict, *, days_inactive: int, warning_days: int) -> bool:
    url = _public_url(cfg)
    return send_blinq_transactional_email(
        cfg,
        str(user.get("email") or ""),
        subject=f"BlinQ · Tvoj účet bude o {warning_days} dní označený ako neaktívny",
        eyebrow="BLINQ ACCOUNT",
        title_sk="Zostaň s BlinQ aktívny",
        body_sk=(
            f"Tvoj BlinQ účet je už približne {days_inactive} dní bez aktivity. "
            f"Stačí sa do {warning_days} dní prihlásiť a účet zostane aktívny.\n\n"
            "Ak sa neprihlásiš, účet označíme ako EXPIRED. Firebase účet ani tvoje údaje tým automaticky nemažeme."
        ),
        title_en="Keep your BlinQ account active",
        body_en=(
            f"Your BlinQ account has been inactive for about {days_inactive} days. "
            f"Sign in within {warning_days} days to keep it active.\n\n"
            "If you do not sign in, the account will be marked EXPIRED. This does not automatically delete your Firebase account or data."
        ),
        button_label="Prihlásiť sa do BlinQ / Sign in to BlinQ" if url else "",
        button_url=url,
        footer_sk="Toto je automatické bezpečnostné upozornenie k účtu BlinQ.",
        footer_en="This is an automated BlinQ account notice.",
    )


def _send_inactivity_expired(cfg, user: dict) -> bool:
    url = _public_url(cfg)
    return send_blinq_transactional_email(
        cfg,
        str(user.get("email") or ""),
        subject="BlinQ · Účet bol označený ako EXPIRED",
        eyebrow="BLINQ ACCOUNT",
        title_sk="Účet je neaktívny",
        body_sk=(
            "Po predchádzajúcom upozornení a ďalšom období bez aktivity bol tvoj FREE ROOKIE prístup označený ako EXPIRED. "
            "Firebase účet nebol automaticky vymazaný ani deaktivovaný."
        ),
        title_en="Your account is inactive",
        body_en=(
            "After the previous warning and a further period without activity, your FREE ROOKIE access was marked EXPIRED. "
            "Your Firebase account was not automatically deleted or disabled."
        ),
        button_label="Otvoriť BlinQ / Open BlinQ" if url else "",
        button_url=url,
    )


def _send_subscription_expiry(cfg, user: dict, access: dict, *, days: int, expiry: datetime) -> bool:
    url = _public_url(cfg)
    raw_plan = str(access.get("plan") or "").lower()
    plan = {"pro": "PRO", "elite": "ELITE", "legend": "Legend", "goat": "GOAT"}.get(
        raw_plan, str(access.get("plan_label") or access.get("plan") or "BlinQ").replace("BlinQ ", "").strip()
    )
    sk_expiry, en_expiry = _format_expiry(expiry)
    return send_blinq_transactional_email(
        cfg,
        str(user.get("email") or ""),
        subject=f"BlinQ · {plan} predplatné končí o {days} dní / Subscription ends in {days} days",
        eyebrow="BLINQ MEMBERSHIP",
        title_sk=f"Tvoje {plan} predplatné končí o {days} dní",
        body_sk=(
            f"Platený prístup {plan} je aktívny do {sk_expiry}.\n\n"
            "Po skončení sa platený prístup ukončí, ale tvoj BlinQ účet zostane zachovaný."
        ),
        title_en=f"Your {plan} subscription ends in {days} days",
        body_en=(
            f"Your paid {plan} access is active until {en_expiry}.\n\n"
            "When it expires, paid access ends, but your BlinQ account remains available."
        ),
        button_label="Otvoriť BlinQ / Open BlinQ" if url else "",
        button_url=url,
        footer_sk="Ak už bolo predplatné predĺžené, nová platnosť sa zohľadní pri ďalšej dennej kontrole.",
        footer_en="If the subscription has already been extended, the new expiry will be picked up by the next daily review.",
    )


def _admin_summary_body(policy: dict, warnings: list[dict], expired: list[dict], paid7: list[dict], paid3: list[dict], failures: list[str]) -> str:
    lines = [
        "Denný account lifecycle prebehol.",
        "",
        f"ROOKIE: EXPIRED po {policy['inactive_days']} dňoch neaktivity · warning {policy['warning_days']} dní vopred",
        f"Nové inactivity warningy: {len(warnings)}",
        f"Novo označené EXPIRED: {len(expired)}",
        f"Paid expiry 7-day maily: {len(paid7)}",
        f"Paid expiry 3-day maily: {len(paid3)}",
        f"Chyby jednotlivých mailov: {len(failures)}",
    ]
    for title, rows in (("Inactivity warnings", warnings), ("EXPIRED", expired), ("Paid 7d", paid7), ("Paid 3d", paid3)):
        if rows:
            lines += ["", f"{title}:"]
            for row in rows[:30]:
                extra = f" · {row.get('plan', '')}" if row.get("plan") else ""
                lines.append(f"- {row.get('email') or row.get('id')}{extra}")
    if failures:
        lines += ["", "Mail failures:"] + [f"- {item}" for item in failures[:30]]
    return "\n".join(lines)


def _send_admin_summary(cfg, body: str) -> int:
    sent = 0
    for recipient in admin_recipients(cfg):
        try:
            if send_blinq_transactional_email(
                cfg,
                recipient,
                subject="BlinQ · Denný account lifecycle súhrn",
                eyebrow="BLINQ ADMIN",
                title_sk="Denný súhrn účtov",
                body_sk=body,
                title_en="Daily account summary",
                body_en="This operational message contains the BlinQ account lifecycle summary. The detailed event list is shown above.",
                button_label="Otvoriť BlinQ / Open BlinQ" if _public_url(cfg) else "",
                button_url=_public_url(cfg),
            ):
                sent += 1
        except Exception:
            # Admin notification failure must not roll back user lifecycle state.
            continue
    return sent


def _subscription_notice_due(expiry: datetime, now: datetime) -> int | None:
    seconds = (expiry - now).total_seconds()
    if seconds <= 0:
        return None
    remaining = max(1, ceil(seconds / 86400))
    if remaining <= 3:
        return 3
    if remaining <= 7:
        return 7
    return None


def run_inactivity_review(cfg, runtime_config: object, *, now=None) -> dict:
    """Run the daily inactivity + paid expiry review.

    Function name is retained for route/backward compatibility.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Account lifecycle review requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    policy = inactivity_policy(runtime_config)
    mail = smtp_diagnostics(cfg)
    summary = {
        "enabled": policy["enabled"],
        "scanned_at": now.isoformat(),
        "scanned": 0,
        "inactive": 0,
        "warnings": 0,
        "expired": 0,
        "subscription_7": 0,
        "subscription_3": 0,
        "user_emails": 0,
        "mail_failures": 0,
        "admin_email": False,
        "admin_emails": 0,
        "storage_available": True,
        "smtp_configured": mail["configured"],
        "admin_recipient_configured": mail["admin_recipient_configured"],
        "admin_recipient_count": mail.get("admin_recipient_count", 0),
        "auto_expire_effective": bool(policy["auto_expire_rookie"] and policy["notify_user"] and mail["configured"]),
        "policy": policy,
        "last_error": "",
    }
    users = []
    for page in range(1, 26):
        batch = list_users(cfg, page=page, per_page=200)
        users.extend(batch)
        if len(batch) < 200:
            break
    summary["scanned"] = len(users)

    new_warnings: list[dict] = []
    newly_expired: list[dict] = []
    paid7: list[dict] = []
    paid3: list[dict] = []
    failures: list[str] = []

    for user in users:
        if is_admin(user, cfg):
            continue
        uid = str(user.get("id") or "")
        email = str(user.get("email") or "")
        meta_available = True
        try:
            meta = load_account_metadata(uid)
        except AdminStorageUnavailable:
            meta = {}
            meta_available = False
            summary["storage_available"] = False

        access = account_access(user, cfg=cfg, now=now)
        plan = str(access.get("plan") or "rookie").lower()
        status = str(access.get("status") or "").lower()

        # Paid membership reminders are independent from inactivity policy.
        expiry = _parse_utc(access.get("expires_at"))
        if plan in {"pro", "elite", "legend", "goat"} and status == "active" and expiry and email and mail["configured"]:
            due = _subscription_notice_due(expiry, now)
            if due:
                marker = str(meta.get(f"subscription_expiry_{due}_for") or "")
                exact_expiry = expiry.isoformat()
                if marker != exact_expiry and meta_available:
                    try:
                        if _send_subscription_expiry(cfg, user, access, days=due, expiry=expiry):
                            summary["user_emails"] += 1
                            save_subscription_notice_state(uid, days=due, expires_for=exact_expiry, sent_at=now.isoformat())
                            row = {"id": uid, "email": email, "plan": plan.upper(), "expires_at": exact_expiry}
                            (paid3 if due == 3 else paid7).append(row)
                    except Exception as exc:
                        summary["mail_failures"] += 1
                        failures.append(f"{email or uid} · paid {due}d · {exc.__class__.__name__}")

        # Inactivity housekeeping is separately configurable and only applies
        # to the permanent free ROOKIE base. Paid expiry reminders above remain
        # active even when inactivity housekeeping is disabled.
        if not policy["enabled"] or plan != "rookie" or status != "active":
            continue
        last_seen = _last_seen(user, meta)
        if not last_seen:
            continue
        days_inactive = max(0, int((now - last_seen).total_seconds() // 86400))
        warning_threshold = policy["inactive_days"] - policy["warning_days"]
        if days_inactive < warning_threshold:
            continue
        summary["inactive"] += 1

        warning_sent_at = _parse_utc(meta.get("inactivity_deactivation_warning_sent_at"))
        warning_already_sent = _marker_is_for_current_inactivity(meta.get("inactivity_deactivation_warning_sent_at"), last_seen)
        row = {
            "id": uid,
            "email": email,
            "plan": "ROOKIE",
            "days_inactive": days_inactive,
            "last_seen": last_seen.isoformat(),
        }

        if policy["notify_user"] and email and mail["configured"] and meta_available and not warning_already_sent:
            try:
                if _send_inactivity_warning(cfg, user, days_inactive=days_inactive, warning_days=policy["warning_days"]):
                    summary["user_emails"] += 1
                    # Persist immediately after this irreversible side effect;
                    # one later user's SMTP failure cannot erase this marker.
                    save_inactivity_state(
                        uid,
                        warning_sent_at=now.isoformat(),
                        user_warning_sent_at=now.isoformat(),
                        deactivation_warning_sent_at=now.isoformat(),
                    )
                    warning_sent_at = now
                    warning_already_sent = True
                    new_warnings.append(row)
            except Exception as exc:
                summary["mail_failures"] += 1
                failures.append(f"{email or uid} · inactivity warning · {exc.__class__.__name__}")

        # Never expire on the same run as the warning: a full warning window must
        # elapse from actual successful send. Re-read identity + activity just
        # before the state transition to close the login-during-review race.
        expire_due = days_inactive >= policy["inactive_days"]
        warning_lead_elapsed = bool(
            warning_sent_at
            and warning_sent_at >= last_seen
            and now >= warning_sent_at + timedelta(days=policy["warning_days"])
        )
        already_expired_for_cycle = _marker_is_for_current_inactivity(meta.get("inactivity_expired_at"), last_seen)
        if expire_due and policy["auto_expire_rookie"] and meta_available and warning_already_sent and warning_lead_elapsed and not already_expired_for_cycle:
            try:
                latest_user = firebase_get_user(cfg, uid) or user
                latest_meta = load_account_metadata(uid)
                latest_seen = _last_seen(latest_user, latest_meta)
            except Exception as exc:
                # Fail closed: no EXPIRED transition when final activity state
                # cannot be proven current.
                summary["storage_available"] = False
                failures.append(f"{email or uid} · final activity recheck · {exc.__class__.__name__}")
                continue
            latest_days = max(0, int((now - latest_seen).total_seconds() // 86400)) if latest_seen else 0
            latest_warning = _parse_utc(latest_meta.get("inactivity_deactivation_warning_sent_at"))
            if latest_days < policy["inactive_days"] or not latest_warning or latest_warning < latest_seen:
                continue
            if now < latest_warning + timedelta(days=policy["warning_days"]):
                continue
            update_user_access(
                cfg,
                uid,
                {"role": "user", "plan": "rookie", "status": "expired", "expires_at": None},
                actor_id="account-lifecycle-worker",
            )
            save_inactivity_state(uid, expired_at=now.isoformat())
            newly_expired.append({"id": uid, "email": email, "days_inactive": latest_days, "plan": "ROOKIE"})
            if email and mail["configured"]:
                try:
                    if _send_inactivity_expired(cfg, latest_user):
                        summary["user_emails"] += 1
                except Exception as exc:
                    summary["mail_failures"] += 1
                    failures.append(f"{email or uid} · inactivity expired · {exc.__class__.__name__}")

    summary["warnings"] = len(new_warnings)
    summary["expired"] = len(newly_expired)
    summary["subscription_7"] = len(paid7)
    summary["subscription_3"] = len(paid3)

    if policy["notify_admin"] and mail["configured"] and mail["admin_recipient_configured"] and (new_warnings or newly_expired or paid7 or paid3 or failures):
        count = _send_admin_summary(cfg, _admin_summary_body(policy, new_warnings, newly_expired, paid7, paid3, failures))
        summary["admin_emails"] = count
        summary["admin_email"] = count > 0

    return summary
