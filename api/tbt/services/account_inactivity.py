"""Optional inactivity review for BlinQ accounts.

ROOKIE itself is unlimited. This worker is a separate, configurable operational
policy: it can report dormant accounts, send warning e-mails and (only when the
admin explicitly enables it) archive long-inactive free ROOKIE access.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
import smtplib
import ssl

from .account_storage import load_account_metadata, save_inactivity_state
from .admin_accounts import list_users, update_user_access
from .admin_storage import AdminStorageUnavailable
from .auth import account_access, is_admin


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
        inactive_days = int(raw.get("inactive_days", 90))
    except (TypeError, ValueError):
        inactive_days = 90
    inactive_days = max(14, min(3650, inactive_days))
    try:
        warning_days = int(raw.get("warning_days", 7))
    except (TypeError, ValueError):
        warning_days = 7
    warning_days = max(1, min(inactive_days - 1, warning_days))
    return {
        "enabled": raw.get("enabled", True) is not False,
        "inactive_days": inactive_days,
        "warning_days": warning_days,
        "notify_admin": raw.get("notify_admin", True) is not False,
        "notify_user": raw.get("notify_user", False) is True,
        "auto_expire_rookie": raw.get("auto_expire_rookie", False) is True,
    }


def smtp_diagnostics(cfg) -> dict:
    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    sender = str(getattr(cfg, "blinq_smtp_from", "") or "").strip()
    admin = str(getattr(cfg, "blinq_admin_email", "") or "").strip()
    port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    configured = bool(host and sender and 1 <= port <= 65535)
    return {
        "configured": configured,
        "admin_recipient_configured": bool(admin),
        "host_configured": bool(host),
        "from_configured": bool(sender),
        "port": port,
        "starttls": bool(getattr(cfg, "blinq_smtp_starttls", True)),
    }


def _send_mail(cfg, recipient: str, subject: str, body: str) -> bool:
    recipient = str(recipient or "").strip()
    diag = smtp_diagnostics(cfg)
    if not recipient or not diag["configured"]:
        return False
    msg = EmailMessage()
    msg["Subject"] = str(subject or "BlinQ")[:180]
    msg["From"] = str(getattr(cfg, "blinq_smtp_from", "") or "").strip()
    msg["To"] = recipient
    msg.set_content(str(body or ""))

    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    username = str(getattr(cfg, "blinq_smtp_username", "") or "").strip()
    password = str(getattr(cfg, "blinq_smtp_password", "") or "")
    timeout = 20
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context()) as client:
            if username:
                client.login(username, password)
            client.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as client:
            client.ehlo()
            if bool(getattr(cfg, "blinq_smtp_starttls", True)):
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if username:
                client.login(username, password)
            client.send_message(msg)
    return True


def _last_seen(user: dict):
    return _parse_utc(user.get("last_sign_in_at")) or _parse_utc(user.get("created_at"))


def _marker_is_for_current_inactivity(marker, last_seen) -> bool:
    marked = _parse_utc(marker)
    return bool(marked and last_seen and marked >= last_seen)


def _user_warning_body(user: dict, *, days_inactive: int, days_left: int, will_expire: bool) -> str:
    greeting = str(user.get("email") or "BlinQ člen")
    if will_expire:
        action = (
            f"Ak sa neprihlásiš, FREE ROOKIE prístup bude označený ako neaktívny približne o {max(1, days_left)} dní. "
            "Samotný ROOKIE nemá platenú časovú platnosť; ide iba o správu dlhodobo nepoužívaných účtov."
        )
    else:
        action = "Tvoj FREE ROOKIE prístup je bez časového obmedzenia; toto je iba upozornenie na dlhšiu neaktivitu."
    return (
        f"Ahoj,\n\nna účte {greeting} sme zaznamenali približne {days_inactive} dní bez prihlásenia.\n\n"
        f"{action}\n\nAk účet používaš, stačí sa znovu prihlásiť do BlinQ.\n\nBlinQ"
    )


def _admin_summary_body(policy: dict, warnings: list[dict], expired: list[dict]) -> str:
    lines = [
        "BlinQ · denná kontrola neaktívnych účtov",
        "",
        f"Limit neaktivity: {policy['inactive_days']} dní · upozornenie: {policy['warning_days']} dní vopred",
        f"Auto-expirácia FREE ROOKIE: {'zapnutá' if policy['auto_expire_rookie'] else 'vypnutá'}",
        "",
        f"Nové upozornenia: {len(warnings)}",
        f"Novo expirované ROOKIE: {len(expired)}",
    ]
    if warnings:
        lines += ["", "Upozornenia:"]
        lines.extend(f"- {row['email']} · {row['days_inactive']} dní · {row['plan']}" for row in warnings[:50])
    if expired:
        lines += ["", "Expirované:"]
        lines.extend(f"- {row['email']} · {row['days_inactive']} dní" for row in expired[:50])
    if len(warnings) > 50 or len(expired) > 50:
        lines += ["", "Zoznam je skrátený na 50 položiek v každej skupine."]
    return "\n".join(lines)


def run_inactivity_review(cfg, runtime_config: object, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Inactivity review requires timezone-aware now")
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
        "user_emails": 0,
        "admin_email": False,
        "storage_available": True,
        "smtp_configured": mail["configured"],
        "admin_recipient_configured": mail["admin_recipient_configured"],
        "auto_expire_effective": bool(policy["auto_expire_rookie"] and mail["configured"] and (policy["notify_user"] or (policy["notify_admin"] and mail["admin_recipient_configured"]))),
        "policy": policy,
        "last_error": "",
    }
    if not policy["enabled"]:
        return summary

    users = []
    for page in range(1, 26):
        batch = list_users(cfg, page=page, per_page=200)
        users.extend(batch)
        if len(batch) < 200:
            break
    summary["scanned"] = len(users)

    new_warnings: list[dict] = []
    newly_expired: list[dict] = []
    pending_markers: set[str] = set()

    for user in users:
        if is_admin(user, cfg):
            continue
        last_seen = _last_seen(user)
        if not last_seen:
            continue
        days_inactive = max(0, int((now - last_seen).total_seconds() // 86400))
        if days_inactive < policy["inactive_days"] - policy["warning_days"]:
            continue
        access = account_access(user, cfg=cfg, now=now)
        if str(access.get("status") or "") == "suspended":
            continue
        summary["inactive"] += 1

        meta_available = True
        try:
            meta = load_account_metadata(user.get("id"))
        except AdminStorageUnavailable:
            meta = {}
            meta_available = False
            summary["storage_available"] = False

        # Notify once when the account reaches the warning window, even if the
        # worker is first enabled after the inactivity threshold has already
        # passed. Durable metadata is required so a storage outage cannot turn
        # a daily worker into repeated e-mail spam.
        warning_due = days_inactive >= policy["inactive_days"] - policy["warning_days"]
        warning_already_sent = _marker_is_for_current_inactivity(meta.get("inactivity_warning_sent_at"), last_seen)
        warning_new = bool(meta_available and warning_due and not warning_already_sent)
        if warning_new:
            row = {
                "id": str(user.get("id") or ""),
                "email": str(user.get("email") or ""),
                "plan": str(access.get("plan") or "rookie").upper(),
                "days_inactive": days_inactive,
                "last_seen": last_seen.isoformat(),
            }
            new_warnings.append(row)
            if policy["notify_user"] and row["email"] and mail["configured"]:
                days_left = max(1, policy["inactive_days"] - days_inactive)
                if _send_mail(
                    cfg,
                    row["email"],
                    "BlinQ · upozornenie na neaktívny účet",
                    _user_warning_body(
                        user,
                        days_inactive=days_inactive,
                        days_left=days_left,
                        will_expire=policy["auto_expire_rookie"],
                    ),
                ):
                    summary["user_emails"] += 1
                    pending_markers.add(row["id"])

        expire_due = days_inactive >= policy["inactive_days"]
        # Expiration is intentionally one run behind a successfully recorded
        # warning. That guarantees the optional cleanup policy can never expire
        # a FREE ROOKIE account before at least one notification path succeeded.
        notification_ready = bool(policy["notify_user"] or (policy["notify_admin"] and mail["admin_recipient_configured"]))
        can_auto_expire = bool(policy["auto_expire_rookie"] and mail["configured"] and notification_ready and meta_available and warning_already_sent)
        already_expired_for_cycle = _marker_is_for_current_inactivity(meta.get("inactivity_expired_at"), last_seen)
        if (
            expire_due
            and can_auto_expire
            and not already_expired_for_cycle
            and str(access.get("plan") or "").lower() == "rookie"
            and str(access.get("status") or "").lower() == "active"
        ):
            update_user_access(
                cfg,
                user.get("id"),
                {"role": "user", "plan": "rookie", "status": "expired", "expires_at": None},
                actor_id="account-inactivity-worker",
            )
            newly_expired.append({
                "id": str(user.get("id") or ""),
                "email": str(user.get("email") or ""),
                "days_inactive": days_inactive,
            })
            if summary["storage_available"]:
                save_inactivity_state(user.get("id"), expired_at=now.isoformat())
            if policy["notify_user"] and user.get("email") and mail["configured"]:
                if _send_mail(
                    cfg,
                    str(user.get("email")),
                    "BlinQ · FREE ROOKIE prístup bol označený ako neaktívny",
                    "Ahoj,\n\npre dlhodobú neaktivitu bol tvoj FREE ROOKIE prístup označený ako neaktívny. "
                    "Ak chceš účet znovu používať, kontaktuj BlinQ administrátora.\n\nBlinQ",
                ):
                    summary["user_emails"] += 1

    # Send one compact admin report only when there is something new.
    if policy["notify_admin"] and (new_warnings or newly_expired) and mail["configured"] and mail["admin_recipient_configured"]:
        recipient = str(getattr(cfg, "blinq_admin_email", "") or "").strip()
        summary["admin_email"] = _send_mail(
            cfg,
            recipient,
            "BlinQ · kontrola neaktívnych účtov",
            _admin_summary_body(policy, new_warnings, newly_expired),
        )
        if summary["admin_email"]:
            pending_markers.update(row["id"] for row in new_warnings)

    if summary["storage_available"]:
        for uid in sorted(pending_markers):
            save_inactivity_state(uid, warning_sent_at=now.isoformat())

    summary["warnings"] = len(new_warnings)
    summary["expired"] = len(newly_expired)
    return summary
