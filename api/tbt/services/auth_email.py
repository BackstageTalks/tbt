"""BlinQ-branded transactional e-mails.

Firebase remains the identity authority. The Admin SDK only creates one-time
action codes; BlinQ owns the SMTP transport and the SK/EN presentation.

The same renderer/transport is shared by auth, inactivity and subscription
lifecycle notices so all account e-mails keep one visual language.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr
from html import escape as html_escape
import hashlib
import smtplib
import ssl
from urllib.parse import urlsplit, urlunsplit

from .auth import AuthUnavailable, firebase_app, _firebase_modules
from .admin_storage import AdminStorageUnavailable, _table

_AUTH_EMAIL_THROTTLE_TABLE = "BlinQAuthEmailThrottle"


def _resource_exists(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    name = exc.__class__.__name__.lower()
    return status == 409 or "resourceexists" in name or "alreadyexists" in name or "conflict" in name


def claim_auth_email_slot(recipient: str, kind: str, *, window_seconds: int = 90) -> bool:
    """Atomically claim a short SMTP delivery slot without storing the address."""
    normalized = str(recipient or "").strip().lower()
    action = str(kind or "").strip().lower()
    if action not in {"verify", "reset"} or not normalized or "@" not in normalized:
        raise ValueError("Invalid auth email throttle key")
    seconds = max(30, min(900, int(window_seconds or 90)))
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp()) // seconds
    digest = hashlib.sha256(f"{action}|{normalized}|{bucket}".encode("utf-8")).hexdigest()
    entity = {
        "PartitionKey": now.strftime("%Y%m%d"),
        "RowKey": digest,
        "kind": action,
        "bucket": bucket,
        "created_at": now.isoformat(),
    }
    try:
        _table(_AUTH_EMAIL_THROTTLE_TABLE).create_entity(entity)
        return True
    except Exception as exc:
        if _resource_exists(exc):
            return False
        raise AdminStorageUnavailable("Auth email throttle storage unavailable") from exc


def _smtp_ready(cfg) -> bool:
    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    sender = str(getattr(cfg, "blinq_smtp_from", "") or "").strip()
    try:
        port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    except (TypeError, ValueError):
        return False
    return bool(host and sender and 1 <= port <= 65535)


def _public_url(cfg) -> str:
    value = str(getattr(cfg, "blinq_public_url", "") or "").strip().rstrip("/")
    if not value.startswith("https://"):
        raise ValueError("BLINQ_PUBLIC_URL must be an https URL")
    return value


def _action_link(firebase_link: str, cfg) -> str:
    parsed = urlsplit(str(firebase_link or ""))
    if not parsed.query:
        raise AuthUnavailable("Firebase action link is invalid")
    public = urlsplit(_public_url(cfg))
    return urlunsplit((public.scheme, public.netloc, "/auth/action", parsed.query, ""))


def _firebase_action_link(cfg, kind: str, email: str) -> str:
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    normalized = str(email or "").strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 320:
        raise ValueError("Invalid email")
    try:
        if kind == "verify":
            raw = firebase_auth.generate_email_verification_link(normalized, app=app)
        elif kind == "reset":
            raw = firebase_auth.generate_password_reset_link(normalized, app=app)
        else:
            raise ValueError("Invalid email action")
    except ValueError:
        raise
    except Exception as exc:
        raise AuthUnavailable("Firebase action link could not be created") from exc
    return _action_link(raw, cfg)


def render_blinq_email(
    *,
    eyebrow: str,
    title_sk: str,
    body_sk: str,
    title_en: str,
    body_en: str,
    button_label: str = "",
    button_url: str = "",
    footer_sk: str = "",
    footer_en: str = "",
) -> tuple[str, str]:
    """Return plain + HTML bodies using the canonical BlinQ transactional style."""
    button_label = str(button_label or "").strip()
    button_url = str(button_url or "").strip()
    footer_sk = str(footer_sk or "").strip()
    footer_en = str(footer_en or "").strip()

    plain_parts = [str(title_sk), str(body_sk)]
    if button_url:
        plain_parts += [button_url]
    plain_parts += ["---", str(title_en), str(body_en)]
    if button_url:
        plain_parts += [button_url]
    if footer_sk or footer_en:
        plain_parts += ["", footer_sk, footer_en]
    plain = "\n\n".join(part for part in plain_parts if part).strip() + "\n"

    safe = {k: html_escape(str(v or "")) for k, v in {
        "eyebrow": eyebrow,
        "title_sk": title_sk,
        "body_sk": body_sk,
        "title_en": title_en,
        "body_en": body_en,
        "button_label": button_label,
        "button_url": button_url,
        "footer_sk": footer_sk,
        "footer_en": footer_en,
    }.items()}
    for key in ("body_sk", "body_en", "footer_sk", "footer_en"):
        safe[key] = safe[key].replace("\n", "<br>")

    button = ""
    if button_label and button_url:
        button = (
            f'<div style="margin:24px 0"><a href="{safe["button_url"]}" '
            'style="display:inline-block;background:#43e6a0;color:#03110d;text-decoration:none;font-weight:800;'
            f'border-radius:10px;padding:13px 19px">{safe["button_label"]}</a></div>'
        )
    footer = ""
    if footer_sk or footer_en:
        footer = (
            '<p style="margin:24px 0 0;color:#607b72;font-size:11px;line-height:1.55">'
            f'{safe["footer_sk"]}'
            + ("<br>" if footer_sk and footer_en else "")
            + f'{safe["footer_en"]}</p>'
        )

    html = f'''<!doctype html><html><body style="margin:0;background:#020c0b;color:#eaf6f1;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#020c0b;padding:28px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#061713;border:1px solid #164c3b;border-radius:18px;overflow:hidden">
<tr><td style="padding:28px 30px 18px"><span style="display:inline-block;color:#f3fbf8;font-family:Arial,Helvetica,sans-serif;font-size:30px;font-weight:800;letter-spacing:-1px;line-height:1.1">Blin<span style="color:#43e6a0">Q</span></span></td></tr>
<tr><td style="padding:6px 30px 30px"><div style="font-size:12px;letter-spacing:.16em;color:#45e7a2;font-weight:700">{safe["eyebrow"]}</div>
<h1 style="margin:10px 0 8px;font-size:27px;line-height:1.2;color:#f3fbf8">{safe["title_sk"]}</h1>
<p style="margin:0;color:#a9c2b9;font-size:15px;line-height:1.65">{safe["body_sk"]}</p>
{button}
<div style="height:1px;background:#143a30;margin:22px 0"></div>
<h2 style="margin:0 0 8px;font-size:20px;color:#eaf6f1">{safe["title_en"]}</h2>
<p style="margin:0;color:#8fa9a0;font-size:14px;line-height:1.65">{safe["body_en"]}</p>
{footer}</td></tr></table></td></tr></table></body></html>'''
    return plain, html


def _build_transactional_message(cfg, recipient: str, subject: str, plain: str, html: str) -> EmailMessage:
    """Create RFC 5322-compliant auth/lifecycle mail without image attachments.

    The configured SMTP provider, not the application, must DKIM-sign outbound
    messages for the verified sending domain. Date/Message-ID alone cannot
    repair SPF, DKIM, DMARC or a sending domain's reputation.
    """
    sender = str(getattr(cfg, "blinq_smtp_from", "") or "").strip()
    mailbox = parseaddr(sender)[1]
    domain = mailbox.rpartition("@")[2].strip().lower()
    if not mailbox or not domain or "." not in domain:
        raise ValueError("BLINQ_SMTP_FROM must contain a valid sender mailbox")

    msg = EmailMessage()
    msg["Subject"] = str(subject or "BlinQ")[:180]
    msg["From"] = sender
    msg["To"] = str(recipient or "").strip()
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(idstring="blinq", domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    return msg


def send_blinq_transactional_email(
    cfg,
    recipient: str,
    *,
    subject: str,
    eyebrow: str,
    title_sk: str,
    body_sk: str,
    title_en: str,
    body_en: str,
    button_label: str = "",
    button_url: str = "",
    footer_sk: str = "",
    footer_en: str = "",
) -> bool:
    """Send one branded BlinQ transactional message."""
    recipient = str(recipient or "").strip()
    if not recipient or "@" not in recipient or len(recipient) > 320:
        raise ValueError("Invalid recipient")
    if not _smtp_ready(cfg):
        raise RuntimeError("SMTP is not configured")
    plain, html = render_blinq_email(
        eyebrow=eyebrow,
        title_sk=title_sk,
        body_sk=body_sk,
        title_en=title_en,
        body_en=body_en,
        button_label=button_label,
        button_url=button_url,
        footer_sk=footer_sk,
        footer_en=footer_en,
    )
    msg = _build_transactional_message(cfg, recipient, subject, plain, html)

    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    username = str(getattr(cfg, "blinq_smtp_username", "") or "").strip()
    password = str(getattr(cfg, "blinq_smtp_password", "") or "")
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=20)
    with client:
        if port != 465:
            client.ehlo()
            if bool(getattr(cfg, "blinq_smtp_starttls", True)):
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(msg)
    return True


def _content(kind: str, action_url: str) -> tuple[str, str, str]:
    if kind == "verify":
        subject = "BlinQ · Overenie e-mailu / Verify your email"
        plain, html = render_blinq_email(
            eyebrow="BLINQ INTELLIGENCE",
            title_sk="Overte svoj e-mail",
            body_sk="Dokončite vytvorenie účtu BlinQ overením e-mailovej adresy.",
            title_en="Verify your email",
            body_en="Complete your BlinQ account by verifying your email address.",
            button_label="Overiť e-mail / Verify email",
            button_url=action_url,
            footer_sk="Ak ste o túto správu nežiadali, môžete ju ignorovať.",
            footer_en="If you did not request this message, you can ignore it.",
        )
    else:
        subject = "BlinQ · Obnova hesla / Reset your password"
        plain, html = render_blinq_email(
            eyebrow="BLINQ INTELLIGENCE",
            title_sk="Obnovte svoje heslo",
            body_sk="Kliknite na tlačidlo nižšie a nastavte si nové heslo k účtu BlinQ.",
            title_en="Reset your password",
            body_en="Use the button below to set a new password for your BlinQ account.",
            button_label="Obnoviť heslo / Reset password",
            button_url=action_url,
            footer_sk="Ak ste o túto správu nežiadali, môžete ju ignorovať.",
            footer_en="If you did not request this message, you can ignore it.",
        )
    return subject, plain, html


def send_blinq_action_email(cfg, recipient: str, kind: str) -> bool:
    action_url = _firebase_action_link(cfg, kind, recipient)
    subject, plain, html = _content(kind, action_url)
    if not _smtp_ready(cfg):
        raise RuntimeError("SMTP is not configured")
    msg = _build_transactional_message(cfg, recipient, subject, plain, html)

    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    username = str(getattr(cfg, "blinq_smtp_username", "") or "").strip()
    password = str(getattr(cfg, "blinq_smtp_password", "") or "")
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=20)
    with client:
        if port != 465:
            client.ehlo()
            if bool(getattr(cfg, "blinq_smtp_starttls", True)):
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(msg)
    return True
