"""Optional inactivity review for BlinQ accounts.

ROOKIE itself is unlimited. This worker is a separate, configurable operational
policy: it can report dormant accounts, send warning e-mails and (only when the
admin explicitly enables it) archive long-inactive free ROOKIE access.

Safety invariant: automatic deactivation is never allowed until the user has
successfully received an inactivity warning and the configured warning period
has elapsed since that actual delivery time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape as html_escape
from pathlib import Path
import smtplib
import ssl

from .account_storage import load_account_metadata, save_inactivity_state
from .admin_accounts import list_users, update_user_access
from .admin_storage import AdminStorageUnavailable
from .auth import account_access, is_admin

_LOGO = Path(__file__).resolve().parents[1] / "assets" / "blinq_logo_email.png"


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
    auto_expire = raw.get("auto_expire_rookie", False) is True
    # User notification is ON by default. If automatic deactivation is enabled,
    # the warning cannot be disabled because it is a prerequisite for expiry.
    notify_user = raw.get("notify_user", True) is not False
    if auto_expire:
        notify_user = True
    return {
        "enabled": raw.get("enabled", True) is not False,
        "inactive_days": inactive_days,
        "warning_days": warning_days,
        "notify_admin": raw.get("notify_admin", True) is not False,
        "notify_user": notify_user,
        "auto_expire_rookie": auto_expire,
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
    plain = str(body or "")
    msg.set_content(plain)
    safe_subject = html_escape(str(subject or "BlinQ"))
    safe_body = html_escape(plain).replace("\n", "<br>")
    html = f"""<!doctype html><html><body style=\"margin:0;background:#020c0b;color:#eaf6f1;font-family:Arial,Helvetica,sans-serif\">
<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"background:#020c0b;padding:28px 12px\"><tr><td align=\"center\">
<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:620px;background:#061713;border:1px solid #164c3b;border-radius:18px;overflow:hidden\">
<tr><td style=\"padding:28px 30px 18px\"><img src=\"cid:blinq-logo\" width=\"150\" alt=\"BlinQ\" style=\"display:block;width:150px;height:auto;border:0\"></td></tr>
<tr><td style=\"padding:6px 30px 30px\"><div style=\"font-size:12px;letter-spacing:.16em;color:#45e7a2;font-weight:700\">BLINQ ACCOUNT</div>
<h1 style=\"margin:10px 0 16px;font-size:24px;line-height:1.25;color:#f3fbf8\">{safe_subject}</h1>
<p style=\"margin:0;color:#a9c2b9;font-size:14px;line-height:1.7\">{safe_body}</p>
</td></tr></table></td></tr></table></body></html>"""
    msg.add_alternative(html, subtype="html")
    if _LOGO.exists():
        html_part = msg.get_payload()[-1]
        html_part.add_related(_LOGO.read_bytes(), maintype="image", subtype="png", cid="<blinq-logo>", filename="blinq.png")

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


def _user_warning_body(user: dict, *, days_inactive: int, warning_days: int, will_expire: bool) -> str:
    email = str(user.get("email") or "BlinQ člen")
    if will_expire:
        action_sk = (
            f"Ak sa neprihlásiš, účet bude deaktivovaný najskôr o {warning_days} dní od doručenia tohto upozornenia. "
            "Stačí sa prihlásiť do BlinQ a počítadlo neaktivity sa obnoví."
        )
        action_en = (
            f"If you do not sign in, the account may be deactivated no earlier than {warning_days} days after this warning is delivered. "
            "Signing in to BlinQ resets the inactivity period."
        )
    else:
        action_sk = "FREE ROOKIE je bez časového obmedzenia; toto je iba upozornenie na dlhšiu neaktivitu."
        action_en = "FREE ROOKIE has no time limit; this is only an inactivity notice."
    return (
        f"Ahoj,\n\nna účte {email} sme zaznamenali približne {days_inactive} dní bez prihlásenia.\n\n"
        f"{action_sk}\n\nBlinQ\n\n---\n\n"
        f"Hello,\n\nwe noticed approximately {days_inactive} days without a sign-in on {email}.\n\n"
        f"{action_en}\n\nBlinQ"
    )


def _admin_summary_body(policy: dict, warnings: list[dict], expired: list[dict]) -> str:
    lines = [
        "BlinQ · denná kontrola neaktívnych účtov",
        "",
        f"Limit neaktivity: {policy['inactive_days']} dní · upozornenie: {policy['warning_days']} dní vopred",
        f"Auto-deaktivácia FREE ROOKIE: {'zapnutá' if policy['auto_expire_rookie'] else 'vypnutá'}",
        "",
        f"Nové upozornenia: {len(warnings)}",
        f"Novo deaktivované ROOKIE: {len(expired)}",
    ]
    if warnings:
        lines += ["", "Upozornenia:"]
        lines.extend(f"- {row['email']} · {row['days_inactive']} dní · {row['plan']}" for row in warnings[:50])
    if expired:
        lines += ["", "Deaktivované:"]
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
        # Automatic deactivation is effective only when we can actually warn the
        # user. Admin-only mail is never enough to deactivate a user account.
        "auto_expire_effective": bool(policy["auto_expire_rookie"] and policy["notify_user"] and mail["configured"]),
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
    general_warning_markers: set[str] = set()
    user_warning_markers: set[str] = set()
    deactivation_warning_markers: set[str] = set()

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

        warning_due = days_inactive >= policy["inactive_days"] - policy["warning_days"]
        warning_already_recorded = _marker_is_for_current_inactivity(meta.get("inactivity_warning_sent_at"), last_seen)
        user_warning_sent_at = _parse_utc(meta.get("inactivity_user_warning_sent_at"))
        user_warning_already_sent = _marker_is_for_current_inactivity(meta.get("inactivity_user_warning_sent_at"), last_seen)
        deactivation_warning_sent_at = _parse_utc(meta.get("inactivity_deactivation_warning_sent_at"))
        deactivation_warning_already_sent = _marker_is_for_current_inactivity(meta.get("inactivity_deactivation_warning_sent_at"), last_seen)
        warning_new = bool(meta_available and warning_due and not warning_already_recorded)

        row = {
            "id": str(user.get("id") or ""),
            "email": str(user.get("email") or ""),
            "plan": str(access.get("plan") or "rookie").upper(),
            "days_inactive": days_inactive,
            "last_seen": last_seen.isoformat(),
        }
        if warning_new:
            new_warnings.append(row)

        # User warning is independently durable. This means an old admin-only
        # marker can never satisfy the deactivation prerequisite.
        user_notice_missing = not (deactivation_warning_already_sent if policy["auto_expire_rookie"] else user_warning_already_sent)
        if (
            meta_available
            and warning_due
            and policy["notify_user"]
            and row["email"]
            and mail["configured"]
            and user_notice_missing
        ):
            if _send_mail(
                cfg,
                row["email"],
                f"BlinQ · účet bude o {policy['warning_days']} dní deaktivovaný" if policy["auto_expire_rookie"] else "BlinQ · upozornenie na neaktívny účet",
                _user_warning_body(
                    user,
                    days_inactive=days_inactive,
                    warning_days=policy["warning_days"],
                    will_expire=policy["auto_expire_rookie"],
                ),
            ):
                summary["user_emails"] += 1
                user_warning_markers.add(row["id"])
                if policy["auto_expire_rookie"]:
                    deactivation_warning_markers.add(row["id"])
                general_warning_markers.add(row["id"])
                # Treat this delivery as effective immediately for reporting,
                # but not for same-run expiry. The expiry gate below reads only
                # the persisted marker loaded at the start of the run.

        expire_due = days_inactive >= policy["inactive_days"]
        # Guarantee the full configured lead time from actual successful user
        # warning delivery, not merely from the theoretical inactivity threshold.
        warning_lead_elapsed = bool(
            deactivation_warning_sent_at
            and deactivation_warning_sent_at >= last_seen
            and now >= deactivation_warning_sent_at + timedelta(days=policy["warning_days"])
        )
        can_auto_expire = bool(
            policy["auto_expire_rookie"]
            and policy["notify_user"]
            and mail["configured"]
            and meta_available
            and deactivation_warning_already_sent
            and warning_lead_elapsed
        )
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
            if user.get("email") and mail["configured"]:
                if _send_mail(
                    cfg,
                    str(user.get("email")),
                    "BlinQ · účet bol deaktivovaný pre neaktivitu",
                    "Ahoj,\n\npo predchádzajúcom upozornení a ďalšom období bez prihlásenia bol tvoj FREE ROOKIE účet deaktivovaný pre dlhodobú neaktivitu. "
                    "Ak chceš účet znovu používať, kontaktuj BlinQ administrátora.\n\nBlinQ\n\n---\n\n"
                    "Hello,\n\nafter the previous warning and a further period without a sign-in, your FREE ROOKIE account was deactivated for long-term inactivity. "
                    "Contact the BlinQ administrator if you want to reactivate it.\n\nBlinQ",
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
            general_warning_markers.update(row["id"] for row in new_warnings)

    if summary["storage_available"]:
        # Persist user-delivery markers first. Both writes are merge upserts.
        for uid in sorted(user_warning_markers):
            save_inactivity_state(
                uid,
                user_warning_sent_at=now.isoformat(),
                deactivation_warning_sent_at=now.isoformat() if uid in deactivation_warning_markers else None,
                warning_sent_at=now.isoformat(),
            )
        for uid in sorted(general_warning_markers - user_warning_markers):
            save_inactivity_state(uid, warning_sent_at=now.isoformat())

    summary["warnings"] = len(new_warnings)
    summary["expired"] = len(newly_expired)
    return summary
