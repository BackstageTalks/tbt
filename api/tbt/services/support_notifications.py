"""Best-effort external notification for newly created BlinQ support tickets.

Storage is the source of truth. Notification failures never reject a ticket.
When RESEND_API_KEY and BLINQ_SUPPORT_TO_EMAIL are configured, a compact email
is sent through Resend using the existing httpx runtime dependency.
"""
from __future__ import annotations

import html
import os
from typing import Any

import httpx


def _env(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def support_email_configured() -> bool:
    return bool(_env("RESEND_API_KEY") and _env("BLINQ_SUPPORT_TO_EMAIL"))


def notify_support_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    if not support_email_configured():
        return {"configured": False, "sent": False, "reason": "not_configured"}

    api_key = _env("RESEND_API_KEY")
    recipient = _env("BLINQ_SUPPORT_TO_EMAIL")
    sender = _env("BLINQ_SUPPORT_FROM_EMAIL") or "BlinQ Support <support@blinq.sk>"
    ticket_id = str(ticket.get("ticket_id") or "BlinQ")[:80]
    category = str(ticket.get("category") or "other")[:80]
    subject = str(ticket.get("subject") or "")[:160]
    email = str(ticket.get("email") or "")[:254]
    message = str(ticket.get("message") or "")[:5000]
    plan = str(ticket.get("account_plan") or "")[:40]

    safe_message = html.escape(message).replace("\n", "<br>")
    body = (
        f"<h2>New BlinQ support ticket {html.escape(ticket_id)}</h2>"
        f"<p><b>Category:</b> {html.escape(category)}<br>"
        f"<b>Account:</b> {html.escape(plan or 'unknown')}<br>"
        f"<b>Reply to:</b> {html.escape(email)}<br>"
        f"<b>Subject:</b> {html.escape(subject or '—')}</p>"
        f"<p>{safe_message}</p>"
    )
    payload = {
        "from": sender,
        "to": [recipient],
        "reply_to": email,
        "subject": f"[{ticket_id}] {subject or category}",
        "html": body,
    }
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Idempotency-Key": f"support-ticket/{ticket_id}"[:256]},
            json=payload,
            timeout=8.0,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        return {"configured": True, "sent": True, "provider": "resend", "message_id": str(data.get("id") or "")[:160]}
    except Exception as exc:  # ticket persistence must remain independent of email delivery
        return {"configured": True, "sent": False, "provider": "resend", "reason": type(exc).__name__}
