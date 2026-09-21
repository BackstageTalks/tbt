"""BlinQ-branded Firebase action e-mails.

Firebase remains the identity authority.  The Admin SDK only creates one-time
action codes; BlinQ owns the SMTP transport and the SK/EN presentation.
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import smtplib
import ssl
from urllib.parse import urlsplit, urlunsplit

from .auth import AuthUnavailable, firebase_app, _firebase_modules
from .admin_storage import AdminStorageUnavailable, _table

_LOGO = Path(__file__).resolve().parents[1] / "assets" / "blinq_logo_email.png"

_AUTH_EMAIL_THROTTLE_TABLE = "BlinQAuthEmailThrottle"


def _resource_exists(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    name = exc.__class__.__name__.lower()
    return status == 409 or "resourceexists" in name or "alreadyexists" in name or "conflict" in name


def claim_auth_email_slot(recipient: str, kind: str, *, window_seconds: int = 90) -> bool:
    """Atomically claim a short SMTP delivery slot without storing the address.

    Azure/Firestore-backed admin storage is used as the durable cross-instance
    dedupe boundary.  The row key contains only a SHA-256 digest of the
    normalized address, action and time bucket, so the throttle table does not
    become a second account directory.
    """
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


def _content(kind: str, action_url: str) -> tuple[str, str, str]:
    if kind == "verify":
        subject = "BlinQ · Overenie e-mailu / Verify your email"
        sk_title, en_title = "Overte svoj e-mail", "Verify your email"
        sk_body = "Dokončite vytvorenie účtu BlinQ overením e-mailovej adresy."
        en_body = "Complete your BlinQ account by verifying your email address."
        button = "Overiť e-mail / Verify email"
        plain = f"{sk_title}\n{sk_body}\n\n{en_title}\n{en_body}\n\n{action_url}\n"
    else:
        subject = "BlinQ · Obnova hesla / Reset your password"
        sk_title, en_title = "Obnovte svoje heslo", "Reset your password"
        sk_body = "Kliknite na tlačidlo nižšie a nastavte si nové heslo k účtu BlinQ."
        en_body = "Use the button below to set a new password for your BlinQ account."
        button = "Obnoviť heslo / Reset password"
        plain = f"{sk_title}\n{sk_body}\n\n{en_title}\n{en_body}\n\n{action_url}\n"
    html = f'''<!doctype html><html><body style="margin:0;background:#020c0b;color:#eaf6f1;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#020c0b;padding:28px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#061713;border:1px solid #164c3b;border-radius:18px;overflow:hidden">
<tr><td style="padding:28px 30px 18px"><img src="cid:blinq-logo" width="150" alt="BlinQ" style="display:block;width:150px;height:auto;border:0"></td></tr>
<tr><td style="padding:6px 30px 30px"><div style="font-size:12px;letter-spacing:.16em;color:#45e7a2;font-weight:700">BLINQ INTELLIGENCE</div>
<h1 style="margin:10px 0 8px;font-size:27px;line-height:1.2;color:#f3fbf8">{sk_title}</h1><p style="margin:0;color:#a9c2b9;font-size:15px;line-height:1.6">{sk_body}</p>
<div style="margin:24px 0"><a href="{action_url}" style="display:inline-block;background:#43e6a0;color:#03110d;text-decoration:none;font-weight:800;border-radius:10px;padding:13px 19px">{button}</a></div>
<div style="height:1px;background:#143a30;margin:22px 0"></div>
<h2 style="margin:0 0 8px;font-size:20px;color:#eaf6f1">{en_title}</h2><p style="margin:0;color:#8fa9a0;font-size:14px;line-height:1.6">{en_body}</p>
<p style="margin:24px 0 0;color:#607b72;font-size:11px;line-height:1.55">Ak ste o túto správu nežiadali, môžete ju ignorovať.<br>If you did not request this message, you can ignore it.</p></td></tr></table>
</td></tr></table></body></html>'''
    return subject, plain, html


def send_blinq_action_email(cfg, recipient: str, kind: str) -> bool:
    action_url = _firebase_action_link(cfg, kind, recipient)
    subject, plain, html = _content(kind, action_url)
    host = str(getattr(cfg, "blinq_smtp_host", "") or "").strip()
    sender = str(getattr(cfg, "blinq_smtp_from", "") or "").strip()
    port = int(getattr(cfg, "blinq_smtp_port", 587) or 587)
    if not host or not sender:
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = str(recipient or "").strip()
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    if _LOGO.exists():
        html_part = msg.get_payload()[-1]
        html_part.add_related(_LOGO.read_bytes(), maintype="image", subtype="png", cid="<blinq-logo>", filename="blinq.png")

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
