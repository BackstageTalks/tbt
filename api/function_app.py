from pathlib import Path
import logging

import azure.functions as func

from tbt.config import settings
from tbt.services.auth import AuthUnavailable, public_account, verify_user
from tbt.services.feed import read_feed, visible_feed
import json

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
FEED = Path(__file__).parent / "data/feed.json"


def response(payload, status=200):
    return func.HttpResponse(json.dumps(payload, ensure_ascii=False, allow_nan=False),
        status_code=status, mimetype="application/json",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.route(route="health", methods=["GET"])
def health(req):
    return response({"ok": True, "version": "3.0.0"})


@app.route(route="v1/auth/config", methods=["GET"])
def auth_config(req):
    return response({"enabled": bool(settings.supabase_url and settings.supabase_anon_key),
                     "supabase_url": settings.supabase_url, "anon_key": settings.supabase_anon_key})


@app.route(route="v1/auth/me", methods=["GET"])
def account(req):
    try:
        user = verify_user(req.headers.get("Authorization"), settings)
        return response(public_account(user)) if user else response({"error": "unauthorized"}, 401)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/feed", methods=["GET"])
def feed(req):
    try:
        user = verify_user(req.headers.get("Authorization"), settings)
        if not user:
            return response({"error": "unauthorized"}, 401)
        data = visible_feed(read_feed(FEED))
        data["account"] = public_account(user)
        return response(data)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except (ValueError, OSError, KeyError):
        logging.exception("Serving feed unavailable")
        return response({"error": "feed_unavailable"}, 503)
