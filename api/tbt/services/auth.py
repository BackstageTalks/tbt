"""Supabase is used solely as an identity provider, never as tennis storage."""
from __future__ import annotations

import httpx


class AuthUnavailable(RuntimeError):
    pass


def request_authorization(headers):
    """Return the user bearer token without trusting SWA's rewritten Authorization header."""
    custom = str(headers.get("X-Blinq-Access-Token") or "").strip()
    if custom:
        return custom if custom.lower().startswith("bearer ") else f"Bearer {custom}"
    return headers.get("Authorization")


def verify_user(authorization, cfg, client=None):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token or len(token) > 16384:
        return None
    if not cfg.supabase_url or not cfg.supabase_anon_key:
        raise AuthUnavailable("Authentication is not configured")
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        response = client.get(f"{cfg.supabase_url}/auth/v1/user", headers={
            "apikey": cfg.supabase_anon_key, "Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403):
            return None
        if response.status_code != 200:
            raise AuthUnavailable("Identity service temporarily unavailable")
        user = response.json()
        return user if isinstance(user, dict) and user.get("id") else None
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthUnavailable("Identity service temporarily unavailable") from exc
    finally:
        if own:
            client.close()


def public_account(user):
    metadata = user.get("user_metadata") or {}
    return {"id": user["id"], "email": user.get("email", ""),
            "name": str(metadata.get("display_name") or metadata.get("name") or "Člen BlinQ")[:80]}
