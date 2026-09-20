from pathlib import Path
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
import hashlib
import hmac
import logging
import json
import os
import time
import smtplib

import azure.functions as func

from tbt.config import settings
from tbt.errors import ConfigurationError
from tbt.services.auth import (
    AuthUnavailable,
    auth_provider,
    is_admin,
    is_suspended,
    public_account,
    profile_claims,
    mirror_profile_claims,
    request_authorization,
    update_firebase_profile,
    verify_user,
    firebase_get_user_by_email,
)
from tbt.services.admin_accounts import (
    delete_user_account,
    get_user,
    list_users,
    mirror_admin_metadata_claims,
    tg_private_state,
    update_user_access,
    update_user_identity,
)
from tbt.services.account_storage import (
    load_account_metadata,
    load_account_metadata_many,
    normalize_profile_update,
    normalize_admin_metadata_update,
    record_admin_metadata_audit,
    save_admin_metadata,
    save_profile_metadata,
    record_manual_payment,
    list_manual_payments,
    list_account_audit,
    delete_account_metadata,
)
from tbt.services.admin_storage import (
    AdminStorageUnavailable,
    admin_storage_backend,
    admin_storage_diagnostics,
    banner_analytics_summary,
    load_runtime_ui_config,
    record_banner_event,
    save_runtime_ui_config,
    list_insights,
    save_insight,
    delete_insight,
    mark_insight_read,
    save_live_worker_status,
    load_live_worker_status,
    save_account_worker_status,
    load_account_worker_status,
    live_min_level,
    membership_levels_from,
)
from tbt.services.content_news import news_pool
from tbt.services.media_storage import (
    MediaStorageUnavailable, download_media, media_storage_diagnostics, upload_media,
)
from tbt.services.push_notifications import (
    delete_subscription, push_storage_diagnostics, save_subscription, sync_push_access, webpush_config,
)
from tbt.services.ops_storage import record_system_event, list_system_events
from tbt.services.feed import read_feed, visible_feed
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.entitlements import filter_feed_for_access
from tbt.services.account_inactivity import run_inactivity_review, smtp_diagnostics, inactivity_policy
from tbt.services.live_comeback import (
    scan_comeback_radar, publish_radar_signals, prime_radar_eligible,
    attach_second_set_odds,
)
from tbt.services.auth_email import send_blinq_action_email

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
FEED = Path(__file__).parent / "data/feed.json"
RELEASE = "7.3.6"
API_VERSION = "3.10.0"

# Lightweight abuse guard for the anonymous banner telemetry endpoint. This is intentionally
# instance-local: durable analytics remains in Table Storage, while this only absorbs accidental
# loops / trivial floods without keeping raw client identifiers in memory.
_BANNER_RATE_WINDOW_SECONDS = 60.0
_BANNER_RATE_MAX_EVENTS = 60
_BANNER_RATE_GLOBAL_MAX_EVENTS = 600
_BANNER_RATE_BUCKETS = defaultdict(deque)
_BANNER_RATE_GLOBAL = deque()
_BANNER_RATE_LOCK = Lock()


# Short-lived in-process cache for presentation-only match intelligence.  The
# endpoint can otherwise trigger several provider calls whenever a modal opens.
# Predictive/model features never read from this cache.
_MATCH_INTELLIGENCE_CACHE: dict[str, tuple[float, dict]] = {}
_MATCH_INTELLIGENCE_CACHE_LOCK = Lock()
_MATCH_INTELLIGENCE_TTL_SECONDS = 15 * 60

_LIVE_RADAR_CACHE: tuple[float, dict] | None = None
_LIVE_RADAR_CACHE_LOCK = Lock()
_LIVE_RADAR_TTL_SECONDS = 45
_LIVE_RADAR_LAST_PUBLISHED_SCAN: str | None = None


def _banner_event_allowed(payload):
    client_id = str((payload or {}).get("client_id") or "anonymous")[:256]
    key = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:24]
    now = time.monotonic()
    cutoff = now - _BANNER_RATE_WINDOW_SECONDS
    with _BANNER_RATE_LOCK:
        while _BANNER_RATE_GLOBAL and _BANNER_RATE_GLOBAL[0] < cutoff:
            _BANNER_RATE_GLOBAL.popleft()
        if len(_BANNER_RATE_GLOBAL) >= _BANNER_RATE_GLOBAL_MAX_EVENTS:
            return False
        bucket = _BANNER_RATE_BUCKETS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _BANNER_RATE_MAX_EVENTS:
            return False
        bucket.append(now)
        _BANNER_RATE_GLOBAL.append(now)
        # Keep this best-effort guard bounded on a long-running worker.
        if len(_BANNER_RATE_BUCKETS) > 10000:
            stale = [k for k, values in list(_BANNER_RATE_BUCKETS.items())[:2000] if not values or values[-1] < cutoff]
            for stale_key in stale:
                _BANNER_RATE_BUCKETS.pop(stale_key, None)
    return True


def response(payload, status=200):
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        status_code=status,
        mimetype="application/json",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-BlinQ-Release": RELEASE},
    )


def _verified_user(req):
    return verify_user(request_authorization(req.headers), settings)


def _profile_for(user, *, required=False):
    if not user:
        return {}
    fallback = profile_claims(user)
    try:
        stored = load_account_metadata(user.get("id"))
    except AdminStorageUnavailable:
        if required:
            raise
        logging.warning("Account metadata storage unavailable; using Firebase claim mirror")
        return fallback

    # Durable storage is authoritative once a field has actually been written.
    merged = dict(fallback)
    if stored.get("telegram_nick"):
        merged["telegram_nick"] = stored["telegram_nick"]
    if stored.get("avatar_variant"):
        merged["avatar_variant"] = stored["avatar_variant"]
    if stored.get("admin_metadata_updated_at") is not None:
        merged["tg_private_member"] = bool(stored.get("tg_private_member", False))
    for key in (
        "payment_reference", "admin_note", "profile_updated_at",
        "access_metadata_updated_at", "admin_metadata_updated_at",
        "admin_metadata_updated_by",
        "legal_consent_version", "legal_consent_locale", "legal_consent_at",
    ):
        if stored.get(key) not in (None, ""):
            merged[key] = stored.get(key)
    merged["storage_fallback"] = False
    return merged


def _admin_user(req):
    user = _verified_user(req)
    if not user:
        return None, response({"error": "unauthorized"}, 401)
    if not bool(user.get("email_verified", False)):
        return None, response({"error": "email_not_verified"}, 403)
    if is_suspended(user):
        return None, response({"error": "account_suspended"}, 403)
    if not is_admin(user, settings):
        return None, response({"error": "forbidden"}, 403)
    return user, None


def _admin_account_row(user, profile=None):
    profile = profile if isinstance(profile, dict) else _profile_for(user, required=False)
    account = public_account(user, cfg=settings, profile=profile)
    tg_state = tg_private_state(account, profile)
    return {
        **account,
        "created_at": user.get("created_at"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "payment_reference": str(profile.get("payment_reference") or "")[:120],
        **tg_state,
        "admin_note": str(profile.get("admin_note") or "")[:500],
        "legal_consent_version": str(profile.get("legal_consent_version") or "")[:40],
        "legal_consent_locale": str(profile.get("legal_consent_locale") or "")[:8],
        "legal_consent_at": profile.get("legal_consent_at"),
    }


@app.route(route="health", methods=["GET"])
def health(req):
    return response({"ok": True, "version": API_VERSION, "release": RELEASE, "auth": auth_provider(settings)})


@app.route(route="v1/media/{media_id}", methods=["GET"])
def public_media(req):
    try:
        media_id = str((req.route_params or {}).get("media_id") or "")
        data, content_type, etag = download_media(media_id)
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "X-BlinQ-Release": RELEASE,
        }
        if etag:
            headers["ETag"] = f'"{etag}"'
        return func.HttpResponse(body=data, status_code=200, mimetype=content_type, headers=headers)
    except ValueError:
        return response({"error": "invalid_media_id"}, 400)
    except FileNotFoundError:
        return response({"error": "media_not_found"}, 404)
    except MediaStorageUnavailable:
        return response({"error": "media_storage_unavailable"}, 503)


@app.route(route="v1/auth/config", methods=["GET"])
def auth_config(req):
    provider = auth_provider(settings)
    payload = {"enabled": provider != "none", "provider": provider, "release": RELEASE}
    if provider == "firebase":
        payload.update({
            "project_id": settings.firebase_project_id,
            "auth_domain": f"{settings.firebase_project_id}.firebaseapp.com",
        })
    return response(payload)


@app.route(route="v1/auth/email", methods=["POST"])
def auth_email(req):
    """Send BlinQ-branded Firebase verification or password-reset e-mail."""
    try:
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return response({"error": "invalid_json"}, 400)
        kind = str(payload.get("type") or "").strip().lower()
        if kind not in {"verify", "reset"}:
            return response({"error": "invalid_email_action"}, 400)

        if kind == "verify":
            user = _verified_user(req)
            if not user:
                return response({"error": "unauthorized"}, 401)
            if is_suspended(user):
                return response({"error": "account_suspended"}, 403)
            recipient = str(user.get("email") or "").strip().lower()
            requested = str(payload.get("email") or recipient).strip().lower()
            if not recipient or requested != recipient:
                return response({"error": "email_mismatch"}, 403)
            if bool(user.get("email_verified", False)):
                return response({"ok": True, "accepted": True, "already_verified": True})
            send_blinq_action_email(settings, recipient, "verify")
            return response({"ok": True, "accepted": True})

        recipient = str(payload.get("email") or "").strip().lower()
        if not recipient or "@" not in recipient or len(recipient) > 320:
            return response({"error": "invalid_email"}, 400)
        # Password reset must not reveal whether an address exists.  We still
        # use Firebase Admin for the lookup so no reset e-mail is sent to an
        # unknown account, but the public response is identical either way.
        existing = firebase_get_user_by_email(settings, recipient)
        if existing is not None:
            send_blinq_action_email(settings, recipient, "reset")
        return response({"ok": True, "accepted": True})
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except (RuntimeError, OSError, smtplib.SMTPException):
        logging.exception("BlinQ auth e-mail delivery failed")
        return response({"error": "email_delivery_unavailable"}, 503)


@app.route(route="v1/auth/me", methods=["GET"])
def account(req):
    try:
        user = _verified_user(req)
        return response(public_account(user, cfg=settings, profile=_profile_for(user))) if user else response({"error": "unauthorized"}, 401)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/auth/profile", methods=["PUT"])
def auth_profile(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        if auth_provider(settings) != "firebase":
            return response({"error": "profile_update_unavailable"}, 503)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        normalized = normalize_profile_update(payload)
        verified = bool(user.get("email_verified", False))
        # New accounts may store only their Telegram nickname before email
        # verification so registration can stay one-step. This grants no access.
        if not verified and set((payload or {}).keys()) - {"telegram_nick", "legal_consent_version", "legal_consent_locale"}:
            return response({"error": "email_not_verified"}, 403)
        firebase_payload = {}
        if verified and isinstance(payload, dict) and "display_name" in payload:
            firebase_payload["display_name"] = normalized["display_name"]
        updated = update_firebase_profile(settings, user.get("id"), firebase_payload)
        # Mirror the small non-sensitive profile fields into Firebase claims so
        # Telegram/avatar identity survives a temporary admin-storage outage.
        updated = mirror_profile_claims(settings, user.get("id"), payload)
        try:
            profile = save_profile_metadata(user.get("id"), payload)
            storage_warning = None
        except AdminStorageUnavailable:
            profile = profile_claims(updated)
            storage_warning = "profile_storage_fallback"
        result = public_account(updated, cfg=settings, profile=profile)
        if storage_warning:
            result["storage_warning"] = storage_warning
        return response(result)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "account_storage_unavailable"}, 503)




def _surface_family(value):
    text = str(value or "").strip().lower().replace("_", " ")
    if "clay" in text:
        return "clay"
    if "grass" in text:
        return "grass"
    if "hard" in text:
        return "hard"
    if "carpet" in text:
        return "carpet"
    return text or "unknown"


def _event_side(event, player_id):
    target = str(player_id or "")
    home = event.get("homeTeam") if isinstance(event, dict) else None
    away = event.get("awayTeam") if isinstance(event, dict) else None
    home_id = str((home or {}).get("id") or "") if isinstance(home, dict) else ""
    away_id = str((away or {}).get("id") or "") if isinstance(away, dict) else ""
    if target and target == home_id:
        return 1, away if isinstance(away, dict) else {}
    if target and target == away_id:
        return 2, home if isinstance(home, dict) else {}
    return 0, {}


def _completed_player_events(events, player_id):
    out = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        side, opponent = _event_side(event, player_id)
        if not side:
            continue
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        status_type = str(status.get("type") or "").strip().lower()
        winner = event.get("winnerCode")
        try:
            winner = int(winner)
        except (TypeError, ValueError):
            winner = 0
        if status_type not in {"finished", "ended"} and winner not in {1, 2}:
            continue
        if winner not in {1, 2}:
            continue
        row = dict(event)
        row["_blinq_side"] = side
        row["_blinq_won"] = bool(winner == side)
        row["_blinq_opponent"] = opponent
        out.append(row)
    out.sort(key=lambda item: int(item.get("startTimestamp") or 0), reverse=True)
    return out


def _form_from_events(events, player_id, *, surface=None, limit=35):
    rows = _completed_player_events(events, player_id)
    if surface:
        wanted = _surface_family(surface)
        rows = [row for row in rows if _surface_family(row.get("groundType") or ((row.get("tournament") or {}).get("uniqueTournament") or {}).get("groundType")) == wanted]
    rows = rows[: max(1, int(limit))]
    if not rows:
        return {"matches": 0, "wins": 0, "win_pct": None}
    wins = sum(1 for row in rows if row.get("_blinq_won"))
    return {"matches": len(rows), "wins": wins, "win_pct": wins / len(rows)}


def _h2h_from_events(events, player1_id, player2_id):
    p2 = str(player2_id or "")
    rows = []
    for row in _completed_player_events(events, player1_id):
        opponent = row.get("_blinq_opponent") if isinstance(row.get("_blinq_opponent"), dict) else {}
        if str(opponent.get("id") or "") == p2:
            rows.append(row)
    wins = sum(1 for row in rows if row.get("_blinq_won"))
    return {"player1_wins": wins, "player2_wins": len(rows) - wins, "matches": len(rows), "source": "recent_player_history"}


def _ranking_rows(payload):
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rankings", "data", "results", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _ranking_rows(value)
            if nested:
                return nested
    return []


def _ranking_summary(payload, player_id):
    rows = _ranking_rows(payload)
    target = str(player_id or "")
    if not rows:
        return {}
    def score(row):
        team = row.get("team") if isinstance(row.get("team"), dict) else {}
        exact = str(team.get("id") or row.get("teamId") or row.get("playerId") or "") == target
        rank = row.get("ranking")
        try:
            rank_ok = int(rank) > 0
        except (TypeError, ValueError):
            rank_ok = False
        return (1 if exact else 0, 1 if rank_ok else 0)
    row = max(rows, key=score)
    team = row.get("team") if isinstance(row.get("team"), dict) else {}
    country = team.get("country") if isinstance(team.get("country"), dict) else {}
    return {
        "rank": row.get("ranking"),
        "previous_rank": row.get("previousRanking"),
        "best_rank": row.get("bestRanking"),
        "ranking_points": row.get("points"),
        "country_code": country.get("alpha2") or country.get("code") or "",
    }


def _provider_events(payload):
    return RapidTennisClient._data(payload)



def _feed_match_intelligence(player1_id, player2_id, surface=""):
    """Return serving-feed analytics without any live provider dependency."""
    try:
        feed = read_feed(FEED)
    except Exception:
        return None
    target1, target2 = str(player1_id), str(player2_id)
    keys = (
        "upcoming", "prime_picks", "top_daily_picks", "top_daily", "daily_picks",
        "value_picks", "value", "doubles_picks", "doubles", "ace_picks",
        "aces", "sg_picks", "sets_games", "set_game_picks",
    )
    rows = []
    for key in keys:
        value = feed.get(key) if isinstance(feed, dict) else None
        if isinstance(value, list):
            rows.extend(value)
    markets = feed.get("markets") if isinstance(feed, dict) else None
    if isinstance(markets, dict):
        for value in markets.values():
            if isinstance(value, list):
                rows.extend(value)
    for row in rows:
        if not isinstance(row, dict):
            continue
        p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
        p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
        ids = (str(p1.get("id") or ""), str(p2.get("id") or ""))
        if set(ids) != {target1, target2}:
            continue
        result = {"source": "serving_feed", "surface": _surface_family(surface or row.get("surface")), "custom_id": row.get("custom_id") or ""}
        for label, player in (("player1", p1), ("player2", p2)):
            presentation = player.get("presentation") if isinstance(player.get("presentation"), dict) else {}
            result[label] = {
                "rank": player.get("rank"),
                "previous_rank": player.get("previous_rank"),
                "best_rank": player.get("best_rank"),
                "ranking_points": player.get("ranking_points"),
                "country_code": player.get("country_code") or "",
                "birth_date": player.get("birth_date"),
                "height_cm": player.get("height_cm"),
                "hand": player.get("hand"),
                "birthplace": player.get("birthplace"),
                "residence": player.get("residence"),
                "presentation": presentation,
            }
        pp1 = result["player1"].get("presentation") or {}
        result["h2h"] = {
            "player1_wins": pp1.get("h2h_wins"),
            "player2_wins": pp1.get("h2h_losses"),
            "matches": (pp1.get("h2h_wins") or 0) + (pp1.get("h2h_losses") or 0) if pp1.get("h2h_wins") is not None and pp1.get("h2h_losses") is not None else None,
            "source": "point_in_time_feed",
        }
        return result
    return None


def _h2h_from_provider_payload(payload, player1_id, player2_id):
    events = RapidTennisClient._data(payload)
    if not events and isinstance(payload, dict) and isinstance(payload.get("events"), list):
        events = [row for row in payload["events"] if isinstance(row, dict)]
    if not events:
        return None
    return _h2h_from_events(events, player1_id, player2_id)


def _player_detail_summary(payload):
    if not isinstance(payload, dict):
        return {}
    row = payload
    for key in ("player", "team", "data", "result"):
        value = row.get(key)
        if isinstance(value, dict):
            row = value
            break
    country = row.get("country") if isinstance(row.get("country"), dict) else {}
    birth_ts = row.get("dateOfBirthTimestamp") or row.get("birthTimestamp") or row.get("birth_timestamp")
    return {
        "country_code": country.get("alpha2") or country.get("code") or "",
        "birth_date": row.get("dateOfBirth") or row.get("birthDate") or row.get("birth_date"),
        "birth_timestamp": birth_ts,
        "height_cm": row.get("height") or row.get("heightCm") or row.get("height_cm"),
        "hand": row.get("plays") or row.get("hand") or row.get("handedness") or row.get("playsHand"),
        "birthplace": row.get("birthplace") or row.get("birthPlace") or row.get("placeOfBirth"),
        "residence": row.get("residence") or row.get("currentResidence"),
    }

def _cached_match_intelligence(key):
    now = time.monotonic()
    with _MATCH_INTELLIGENCE_CACHE_LOCK:
        cached = _MATCH_INTELLIGENCE_CACHE.get(key)
        if cached and now - cached[0] <= _MATCH_INTELLIGENCE_TTL_SECONDS:
            return cached[1]
        if cached:
            _MATCH_INTELLIGENCE_CACHE.pop(key, None)
    return None


def _store_match_intelligence(key, payload):
    with _MATCH_INTELLIGENCE_CACHE_LOCK:
        if len(_MATCH_INTELLIGENCE_CACHE) > 500:
            oldest = sorted(_MATCH_INTELLIGENCE_CACHE.items(), key=lambda item: item[1][0])[:100]
            for old_key, _ in oldest:
                _MATCH_INTELLIGENCE_CACHE.pop(old_key, None)
        _MATCH_INTELLIGENCE_CACHE[key] = (time.monotonic(), payload)


@app.route(route="v1/match-intelligence", methods=["GET"])
def match_intelligence(req):
    """Live presentation enrichment for the match-detail modal.

    This endpoint intentionally does not feed the predictive model.  It uses
    current TennisApi history/ranking data only to give members convenient
    research context (Form LXX, surface form, ranking movement/points, H2H).
    """
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        p1 = str(req.params.get("player1_id") or "").strip()
        p2 = str(req.params.get("player2_id") or "").strip()
        surface = str(req.params.get("surface") or "").strip()[:48]
        custom_id = str(req.params.get("custom_id") or "").strip()[:64]
        if not p1.isdigit() or not p2.isdigit() or len(p1) > 12 or len(p2) > 12:
            return response({"error": "invalid_player_ids"}, 400)
        key = f"{p1}:{p2}:{_surface_family(surface)}:{custom_id}"
        cached = _cached_match_intelligence(key)
        if cached is not None:
            return response({**cached, "cached": True})

        feed_result = _feed_match_intelligence(p1, p2, surface)
        try:
            client = RapidTennisClient(settings)
        except Exception:
            if feed_result is not None:
                _store_match_intelligence(key, feed_result)
                return response({**feed_result, "cached": False, "live_provider": False})
            raise
        histories = {}
        rankings = {}
        details = {}
        for pid in (p1, p2):
            events = []
            seen = set()
            # TennisApi returns 30 events/page in the observed contract.  Two
            # pages are enough for a dynamic L35 display while keeping modal
            # enrichment economical.
            for page in (0, 1):
                payload = client.previous_player_matches(pid, page)
                page_rows = _provider_events(payload)
                if not page_rows:
                    break
                for event in page_rows:
                    event_id = str(event.get("id") or event.get("customId") or "")
                    if event_id and event_id in seen:
                        continue
                    if event_id:
                        seen.add(event_id)
                    events.append(event)
                if len(page_rows) < 30:
                    break
            histories[pid] = events
            try:
                rankings[pid] = _ranking_summary(client.player_rankings(pid), pid)
            except Exception:
                logging.exception("Current ranking enrichment unavailable for player %s", pid)
                rankings[pid] = {}
            try:
                details[pid] = _player_detail_summary(client.player_details(pid))
            except Exception:
                logging.exception("Player detail enrichment unavailable for player %s", pid)
                details[pid] = {}

        h2h = None
        if custom_id:
            try:
                h2h = _h2h_from_provider_payload(client.head_to_head_history(custom_id), p1, p2)
            except Exception:
                logging.exception("Direct H2H enrichment unavailable for %s", custom_id)
        if not h2h or not h2h.get("matches"):
            h2h = _h2h_from_events(histories[p1], p1, p2)
        # If the second player's recent history includes older mutual matches,
        # merge them without double-counting provider event ids.
        p1_h2h_ids = {str(row.get("id") or "") for row in _completed_player_events(histories[p1], p1)
                      if str((row.get("_blinq_opponent") or {}).get("id") or "") == p2}
        extra_h2h = []
        for row in _completed_player_events(histories[p2], p2):
            opponent = row.get("_blinq_opponent") if isinstance(row.get("_blinq_opponent"), dict) else {}
            if str(opponent.get("id") or "") != p1:
                continue
            rid = str(row.get("id") or "")
            if rid and rid in p1_h2h_ids:
                continue
            extra_h2h.append(row)
        if extra_h2h:
            p1_extra_wins = sum(1 for row in extra_h2h if not row.get("_blinq_won"))
            h2h["player1_wins"] += p1_extra_wins
            h2h["player2_wins"] += len(extra_h2h) - p1_extra_wins
            h2h["matches"] += len(extra_h2h)

        result = {"source": "tennisapi_live_presentation", "surface": _surface_family(surface), "h2h": h2h}
        for label, pid, opponent_wins_key in (("player1", p1, "player1_wins"), ("player2", p2, "player2_wins")):
            completed = _completed_player_events(histories[pid], pid)
            profile = {
                "history_matches": min(len(completed), 60),
                "surface_history_matches": sum(1 for row in completed if _surface_family(row.get("groundType") or ((row.get("tournament") or {}).get("uniqueTournament") or {}).get("groundType")) == _surface_family(surface)),
                "recent_form": _form_from_events(histories[pid], pid, limit=35),
                "surface_form": _form_from_events(histories[pid], pid, surface=surface, limit=35),
                "h2h_wins": h2h.get(opponent_wins_key),
                "h2h_losses": h2h.get("player2_wins" if opponent_wins_key == "player1_wins" else "player1_wins"),
                "h2h_matches": h2h.get("matches"),
            }
            base = {}
            if feed_result and isinstance(feed_result.get(label), dict):
                base.update(feed_result.get(label) or {})
            base.update({k: v for k, v in details.get(pid, {}).items() if v not in (None, "")})
            base.update({k: v for k, v in rankings.get(pid, {}).items() if v not in (None, "")})
            base["presentation"] = {**((base.get("presentation") or {}) if isinstance(base.get("presentation"), dict) else {}), **profile}
            result[label] = base
        result["live_provider"] = True
        _store_match_intelligence(key, result)
        return response({**result, "cached": False})
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except Exception:
        logging.exception("Match intelligence live enrichment failed")
        # Azure Static Web Apps runtime does not inherit GitHub Actions
        # secrets. The deployed serving feed is therefore the authoritative
        # offline fallback for presentation analytics. Never turn a provider
        # outage/missing runtime secret into an empty modal when the feed
        # already contains point-in-time Form/Surface/H2H/ranking context.
        try:
            fallback = _feed_match_intelligence(
                locals().get("p1", ""),
                locals().get("p2", ""),
                locals().get("surface", ""),
            )
        except Exception:
            fallback = None
        if fallback is not None:
            cache_key = locals().get("key")
            if cache_key:
                _store_match_intelligence(cache_key, fallback)
            return response({**fallback, "cached": False, "live_provider": False})
        return response({"error": "match_intelligence_unavailable"}, 503)


@app.route(route="v1/player-image/{player_id}", methods=["GET"])
def player_image_proxy(req):
    """Serve provider player artwork without exposing the RapidAPI key."""
    raw = str((req.route_params or {}).get("player_id") or "").strip()
    if not raw.isdigit() or not (1 <= len(raw) <= 12):
        return func.HttpResponse(status_code=404)
    try:
        result = RapidTennisClient(settings).player_image(raw)
    except Exception:
        logging.exception("Player image unavailable for %s", raw)
        return func.HttpResponse(status_code=404, headers={"Cache-Control": "public, max-age=300"})
    if not result:
        return func.HttpResponse(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    data, content_type = result
    allowed = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    if content_type not in allowed:
        content_type = "image/png"
    return func.HttpResponse(body=data, status_code=200, mimetype=content_type, headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"})


@app.route(route="v1/tournament-logo/{tournament_id}", methods=["GET"])
def tournament_logo_proxy(req):
    """Serve TennisApi tournament artwork without exposing the RapidAPI key.

    The provider dark logo is preferred by RapidTennisClient.tournament_logo().
    This is presentation-only data and is intentionally cached by browsers/CDNs.
    """
    raw = str((req.route_params or {}).get("tournament_id") or "").strip()
    if not raw.isdigit() or not (1 <= len(raw) <= 12):
        return func.HttpResponse(status_code=404)
    try:
        result = RapidTennisClient(settings).tournament_logo(raw)
    except Exception:
        logging.exception("Tournament logo unavailable for %s", raw)
        return func.HttpResponse(status_code=404, headers={"Cache-Control": "public, max-age=300"})
    if not result:
        return func.HttpResponse(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    data, content_type = result
    allowed = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
    if content_type not in allowed:
        content_type = "image/png"
    return func.HttpResponse(body=data, status_code=200, mimetype=content_type, headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"})

@app.route(route="v1/ui-config", methods=["GET"])
def runtime_ui_config(req):
    try:
        config = load_runtime_ui_config()
        return response({"configured": bool(config), "config": config})
    except AdminStorageUnavailable:
        return response({"error": "ui_config_storage_unavailable", "configured": False, "config": None, "storage_available": False}, 503)


@app.route(route="v1/content/news", methods=["GET"])
def content_news(req):
    try:
        runtime = None
        try:
            runtime = load_runtime_ui_config()
        except AdminStorageUnavailable:
            runtime = None
        return response(news_pool(config=runtime))
    except (ValueError, OSError, TypeError):
        logging.exception("RSS/news content unavailable")
        return response({"items": [], "sources": 0, "error": "news_unavailable"}, 503)


@app.route(route="v1/banner-events", methods=["POST"])
def banner_events(req):
    try:
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return response({"error": "invalid_analytics_event"}, 400)
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 4096:
            return response({"error": "analytics_event_too_large"}, 413)
        if not _banner_event_allowed(payload):
            return response({"error": "rate_limited"}, 429)
        record_banner_event(payload)
        return response({"accepted": True}, 202)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AdminStorageUnavailable:
        return response({"error": "analytics_storage_unavailable"}, 503)


@app.route(route="v1/feed", methods=["GET"])
def feed(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        account_data = public_account(user, cfg=settings, profile=_profile_for(user))
        data = visible_feed(read_feed(FEED))
        try:
            
            try:
                runtime_ui = load_runtime_ui_config()
            except AdminStorageUnavailable:
                runtime_ui = None
            data, entitlements = filter_feed_for_access(data, account_data, runtime_ui)
        except PermissionError:
            return response({"error": "account_suspended"}, 403)
        data["account"] = account_data
        data["entitlements"] = entitlements
        return response(data)
    except AuthUnavailable as exc:
        record_system_event("error", "feed", "Authentication service unavailable while serving feed", details={"error": exc.__class__.__name__})
        return response({"error": "auth_unavailable"}, 503)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        logging.exception("Serving feed unavailable")
        record_system_event("error", "feed", "Serving feed unavailable", details={"error": exc.__class__.__name__})
        return response({"error": "feed_unavailable"}, 503)






def _membership_allowed(account: dict, min_level: str = "rookie") -> bool:
    if account.get("is_admin") or str(account.get("role") or "").lower() == "admin":
        return True
    status = str(account.get("status") or "").lower()
    plan = "rookie" if status == "trial" else str(account.get("plan") or "").lower()
    return status in {"trial", "active", "lifetime"} and plan in set(membership_levels_from(min_level))

def _live_radar_allowed(account: dict) -> bool:
    return _membership_allowed(account, live_min_level())

def _push_allowed(account: dict) -> bool:
    return _membership_allowed(account, "rookie")


def _public_live_radar_payload(result: dict) -> dict:
    candidates=result.get("candidates") or []
    signals=result.get("signals") or []
    public_candidate=lambda x:{k:x.get(k) for k in ("event_id","favorite","opponent","first_set","second_set","stage","reason","tournament","second_set_probability","second_set_model","second_set_quality","second_set_samples","second_set_odds","second_set_fair_probability","second_set_edge","second_set_ev","second_set_market") if k in x}
    return {
        "ok": True,
        "scanned_at": result.get("scanned_at"),
        "live_events": int(result.get("live_events") or 0),
        "candidates": len(candidates) if isinstance(candidates,list) else int(result.get("candidates") or 0),
        "signals": len(signals) if isinstance(signals,list) else int(result.get("signals") or 0),
        "candidate_items": [public_candidate(x) for x in candidates[:3] if isinstance(x,dict)] if isinstance(candidates,list) else list(result.get("candidate_items") or [])[:3],
        "signal_items": [public_candidate(x) for x in signals[:3] if isinstance(x,dict)] if isinstance(signals,list) else list(result.get("signal_items") or [])[:3],
        "new_alerts": int(result.get("created") or result.get("new_alerts") or 0),
        "prime_total": int(result.get("prime_total") or 0),
        "prime_eligible": int(result.get("prime_eligible") or 0),
        "provider_skipped_reason": result.get("provider_skipped_reason"),
        "cached": bool(result.get("cached")),
        "alert_storage_unavailable": bool(result.get("alert_storage_unavailable")),
        "thresholds": result.get("thresholds") or {},
    }


def _live_worker_token_ok(req) -> bool:
    expected=str(os.getenv("BLINQ_LIVE_WORKER_TOKEN") or "").strip()
    supplied=str((getattr(req,"headers",{}) or {}).get("X-Blinq-Worker-Token") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected,supplied))


def _account_worker_token_ok(req) -> bool:
    expected=str(getattr(settings, "blinq_account_worker_token", "") or "").strip()
    supplied=str((getattr(req,"headers",{}) or {}).get("X-Blinq-Worker-Token") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected,supplied))


def _live_worker_snapshot(max_age_seconds: int = 180) -> dict | None:
    try:
        snapshot=load_live_worker_status()
    except AdminStorageUnavailable:
        return None
    if not snapshot or snapshot.get("last_error"):
        return None
    raw=str(snapshot.get("updated_at") or snapshot.get("scanned_at") or "").strip()
    try:
        moment=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if moment.tzinfo is None: moment=moment.replace(tzinfo=timezone.utc)
        age=(datetime.now(timezone.utc)-moment.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        return None
    if age<0 or age>max_age_seconds:
        return None
    return {**snapshot,"cached":True,"worker_snapshot":True}


def _public_live_worker_heartbeat() -> dict:
    """Expose only the non-sensitive autonomous LIVE heartbeat for the footer."""
    snapshot=load_live_worker_status()
    if not snapshot:
        return {"scanned_at": None, "updated_at": None, "fresh": False}
    last_error=bool(snapshot.get("last_error"))
    # Prefer the most recent successful scan. Legacy successful snapshots did
    # not yet carry last_success_at, so their scanned_at remains valid.
    success_raw=str(snapshot.get("last_success_at") or ((snapshot.get("scanned_at") or "") if not last_error else "")).strip()
    raw=success_raw
    age_seconds=None
    fresh=False
    if raw:
        try:
            moment=datetime.fromisoformat(raw.replace("Z","+00:00"))
            if moment.tzinfo is None:
                moment=moment.replace(tzinfo=timezone.utc)
            age_seconds=max(0,int((datetime.now(timezone.utc)-moment.astimezone(timezone.utc)).total_seconds()))
            fresh=age_seconds<=180 and not last_error
        except ValueError:
            pass
    return {
        "scanned_at": success_raw or None,
        "updated_at": snapshot.get("updated_at"),
        "fresh": fresh,
        "age_seconds": age_seconds,
    }


def _run_live_radar(*,force:bool=False,publish:bool=True)->dict:
    """Run/cached LIVE scan and publish idempotent alerts.

    Production scheduling is handled by the autonomous LIVE worker workflow.
    Browser polling is only a freshness fallback when the worker heartbeat is stale.
    """
    global _LIVE_RADAR_CACHE, _LIVE_RADAR_LAST_PUBLISHED_SCAN
    now=time.monotonic(); fresh=False
    with _LIVE_RADAR_CACHE_LOCK:
        if not force and _LIVE_RADAR_CACHE and now-_LIVE_RADAR_CACHE[0]<_LIVE_RADAR_TTL_SECONDS:
            scan=dict(_LIVE_RADAR_CACHE[1]); scan["cached"]=True
        else:
            scan=None
    if scan is None:
        feed_payload=read_feed(FEED)
        prime_pool=feed_payload.get("prime_picks") if isinstance(feed_payload.get("prime_picks"),list) else []
        eligible_pool=[row for row in prime_pool if isinstance(row,dict) and prime_radar_eligible(row)]
        if not eligible_pool:
            # Do not spend a provider request when there is no pre-match PRIME
            # candidate that could possibly qualify for Comeback LIVE.
            scan=scan_comeback_radar(feed_payload,[])
            scan["provider_skipped_reason"]="no_eligible_prime_candidates"
        else:
            client=RapidTennisClient(settings)
            try:
                live_events=client.live_events()
                scan=scan_comeback_radar(feed_payload,live_events)
                odds_payloads={}
                max_odds_events=max(0,min(12,int(os.getenv("BLINQ_LIVE_SET2_ODDS_MAX_EVENTS","6"))))
                for candidate in (scan.get("candidates") or [])[:max_odds_events]:
                    eid=str(candidate.get("event_id") or "").strip() if isinstance(candidate,dict) else ""
                    if not eid:continue
                    try:odds_payloads[eid]=client.event_odds(eid,provider_id=1)
                    except Exception as exc:
                        logging.info("Set-2 odds unavailable for %s: %s",eid,exc.__class__.__name__)
                scan=attach_second_set_odds(scan,odds_payloads,live_events)
            finally:
                try:client.close()
                except Exception:pass
        scan["prime_total"]=len(prime_pool)
        scan["prime_eligible"]=len(eligible_pool)
        scan["cached"]=False; fresh=True
        with _LIVE_RADAR_CACHE_LOCK:_LIVE_RADAR_CACHE=(time.monotonic(),dict(scan))

    pub={"published":[],"created":0,"watch_created":0,"confirmed_created":0}
    storage_unavailable=False
    scan_id=str(scan.get("scanned_at") or "")
    should_publish=bool(publish and scan_id)
    with _LIVE_RADAR_CACHE_LOCK:
        if should_publish and not force and _LIVE_RADAR_LAST_PUBLISHED_SCAN==scan_id:
            should_publish=False
    if should_publish:
        try:
            pub=publish_radar_signals(scan)
            with _LIVE_RADAR_CACHE_LOCK:_LIVE_RADAR_LAST_PUBLISHED_SCAN=scan_id
        except AdminStorageUnavailable:
            storage_unavailable=True
            logging.warning("Comeback LIVE Radar alert storage unavailable")
        except Exception as exc:
            logging.exception("Comeback LIVE Radar alert publish failed")
            return {**scan,**pub,"alert_storage_unavailable":False,"alert_publish_error":exc.__class__.__name__,"fresh_scan":fresh}
    return {**scan,**pub,"alert_storage_unavailable":storage_unavailable,"fresh_scan":fresh}


def _insight_plan_for_user(user):
    """Resolve the membership level used by the private BlinQ Insights feed."""
    profile = _profile_for(user, required=False)
    account = public_account(user, cfg=settings, profile=profile)
    if account.get("is_admin") or str(account.get("role") or "").lower() == "admin":
        # Admins may preview every active audience in the public drawer.
        return ""
    status = str(account.get("status") or "expired").lower()
    if status == "trial":
        return "rookie"
    if status not in {"active", "lifetime"}:
        return "expired"
    return str(account.get("plan") or "expired").lower()


@app.route(route="v1/live-radar", methods=["GET"])
def live_radar(req):
    try:
        user=_verified_user(req)
        if not user:return response({"error":"unauthorized"},401)
        if not bool(user.get("email_verified",False)):return response({"error":"email_not_verified"},403)
        if is_suspended(user):return response({"error":"account_suspended"},403)
        account=public_account(user,cfg=settings,profile=_profile_for(user))
        if not _live_radar_allowed(account):return response({"error":"live_access_required","required_level":live_min_level()},403)
        # Prefer the autonomous worker snapshot. If its heartbeat is stale or
        # durable storage is temporarily unavailable, fall back to one cached
        # on-demand scan so eligible members/admin still get a usable service.
        snapshot=_live_worker_snapshot()
        if snapshot is not None:
            return response({**_public_live_radar_payload(snapshot),"autonomous":True})
        r=_run_live_radar(force=False,publish=True)
        return response({**_public_live_radar_payload(r),"autonomous":False,"fallback_scan":True})
    except AuthUnavailable:return response({"error":"auth_unavailable"},503)
    except AdminStorageUnavailable:return response({"error":"live_radar_storage_unavailable"},503)
    except Exception as exc:
        logging.exception("Comeback LIVE Radar scan failed");return response({"error":"live_radar_unavailable"},503)


@app.route(route="v1/internal/live-radar-worker", methods=["POST"])
def internal_live_radar_worker(req):
    """Secret-protected autonomous scheduler hook; never exposed to browser auth."""
    if not str(os.getenv("BLINQ_LIVE_WORKER_TOKEN") or "").strip():
        return response({"error":"live_worker_not_configured"},503)
    if not _live_worker_token_ok(req):
        return response({"error":"forbidden"},403)
    try:
        result=_run_live_radar(force=True,publish=True)
        public=_public_live_radar_payload(result)
        persisted=True
        try:
            save_live_worker_status(public)
        except AdminStorageUnavailable:
            persisted=False
            logging.warning("LIVE worker heartbeat storage unavailable")
        return response({**public,"autonomous":True,"heartbeat_persisted":persisted})
    except Exception as exc:
        logging.exception("Autonomous LIVE Radar worker failed")
        try:
            previous=load_live_worker_status() or {}
            last_success_at=previous.get("last_success_at") or (previous.get("scanned_at") if not previous.get("last_error") else None)
            save_live_worker_status({
                "scanned_at":datetime.now(timezone.utc).isoformat(),
                "last_success_at":last_success_at,
                "last_error":exc.__class__.__name__,
            })
        except Exception:
            pass
        return response({"error":"live_worker_failed","detail":exc.__class__.__name__},503)


@app.route(route="v1/internal/account-inactivity-worker", methods=["POST"])
def internal_account_inactivity_worker(req):
    """Secret-protected daily account inactivity review hook."""
    if not str(getattr(settings, "blinq_account_worker_token", "") or "").strip():
        return response({"error":"account_worker_not_configured"},503)
    if not _account_worker_token_ok(req):
        return response({"error":"forbidden"},403)
    try:
        try:
            runtime=load_runtime_ui_config() or {}
        except AdminStorageUnavailable:
            # Without runtime storage we can still report using safe defaults, but
            # never auto-expire because the published admin policy is unavailable.
            runtime={"account_inactivity":{"enabled":True,"notify_admin":True,"notify_user":False,"auto_expire_rookie":False}}
        result=run_inactivity_review(settings,runtime)
        persisted=True
        try:
            save_account_worker_status(result)
        except AdminStorageUnavailable:
            persisted=False
            logging.warning("Account inactivity worker heartbeat storage unavailable")
        return response({**result,"heartbeat_persisted":persisted})
    except Exception as exc:
        logging.exception("Account inactivity worker failed")
        try:
            save_account_worker_status({"scanned_at":datetime.now(timezone.utc).isoformat(),"enabled":True,"last_error":exc.__class__.__name__})
        except Exception:
            pass
        return response({"error":"account_worker_failed","detail":exc.__class__.__name__},503)


@app.route(route="v1/admin/live-radar", methods=["GET","POST"])
def admin_live_radar(req):
    admin,error=_admin_user(req)
    if error:return error
    try:
        force=str(req.params.get("force") or "").lower() in {"1","true","yes"} or req.method=="POST"
        return response(_run_live_radar(force=force,publish=req.method=="POST"))
    except AdminStorageUnavailable:return response({"error":"live_radar_storage_unavailable"},503)
    except Exception as exc:
        logging.exception("Admin LIVE Radar scan failed");return response({"error":"live_radar_unavailable","detail":exc.__class__.__name__},503)


@app.route(route="v1/push/config", methods=["GET"])
def push_config(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        account = public_account(user, cfg=settings, profile=_profile_for(user))
        eligible = _push_allowed(account)
        cfg = webpush_config()
        return response({**cfg, "eligible": bool(eligible)})
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/push/subscription", methods=["POST", "DELETE"])
def push_subscription(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        account = public_account(user, cfg=settings, profile=_profile_for(user))
        if not _push_allowed(account):
            return response({"error": "membership_required"}, 403)
        try:
            payload = req.get_json() or {}
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if req.method == "DELETE":
            endpoint = str((payload or {}).get("endpoint") or "")
            return response(delete_subscription(user_id=str(user.get("id") or ""), endpoint=endpoint))
        cfg = webpush_config()
        if not cfg.get("enabled"):
            return response({"error": "webpush_not_configured"}, 503)
        plan = str(account.get("plan") or "").lower()
        push_status = str(account.get("status") or "").lower()
        push_expires_at = account.get("expires_at")
        if push_status == "trial":
            plan = "rookie"
            push_status = "active"
        if account.get("is_admin") or str(account.get("role") or "").lower() == "admin":
            plan = plan if plan in {"elite", "legend", "goat"} else "goat"
            # Admin push is operational access and must not depend on a paid-plan expiry.
            push_status = push_status if push_status in {"active", "lifetime"} else "lifetime"
            if push_status == "lifetime":
                push_expires_at = None
        return response(save_subscription(
            user_id=str(user.get("id") or ""),
            subscription=(payload or {}).get("subscription") or payload,
            plan=plan,
            status=push_status,
            expires_at=push_expires_at,
        ), 201)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AdminStorageUnavailable:
        return response({"error": "push_storage_unavailable"}, 503)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/insights", methods=["GET"])
def insights_feed(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        plan = _insight_plan_for_user(user)
        if plan == "expired":
            try:
                heartbeat=_public_live_worker_heartbeat()
            except AdminStorageUnavailable:
                heartbeat={"scanned_at":None,"updated_at":None,"fresh":False}
            return response({"items": [], "unread": 0, "live_radar_status": heartbeat})
        # INFO can target any active membership level. LIVE items themselves
        # remain server-restricted to the published LIVE minimum by normalize_insight().
        payload = list_insights(plan=plan, user_id=str(user.get("id") or ""), include_inactive=False, limit=100)
        # The homepage footer needs only the autonomous worker heartbeat. It is
        # intentionally separate from the protected LIVE candidates/signals.
        payload["live_radar_status"] = _public_live_worker_heartbeat()
        return response(payload)
    except AdminStorageUnavailable:
        # Insights are optional presentation content. A storage outage must not
        # break the dashboard/feed itself.
        return response({"items": [], "unread": 0, "storage_unavailable": True, "live_radar_status":{"scanned_at":None,"updated_at":None,"fresh":False}})
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/insights/{insight_id}/read", methods=["POST"])
def insights_mark_read(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        insight_id = str((req.route_params or {}).get("insight_id") or "")
        # Verify that the message is actually visible to the caller before
        # accepting a read marker.
        plan = _insight_plan_for_user(user)
        visible = list_insights(plan=plan, user_id=str(user.get("id") or ""), include_inactive=False, limit=250)
        if not any(str(item.get("id") or "") == insight_id for item in visible.get("items", [])):
            return response({"error": "insight_not_available"}, 404)
        return response(mark_insight_read(insight_id=insight_id, user_id=str(user.get("id") or "")))
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)

def _feed_asset_health(raw_feed: dict) -> dict:
    """Describe player/tournament media coverage without spending provider requests."""
    rows = []
    seen_rows = set()
    for key in ("upcoming", "results", "prime_picks", "top_daily_picks", "value_picks", "ace_picks", "sg_picks", "doubles_picks"):
        for row in raw_feed.get(key) or []:
            if not isinstance(row, dict):
                continue
            row_key = str(row.get("id") or row.get("event_id") or row.get("scheduled_at") or id(row))
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append(row)

    players = {}
    tournaments = {}
    for row in rows:
        for side in ("player1", "player2"):
            player = row.get(side) or {}
            if not isinstance(player, dict):
                player = {}
            pid = str(player.get("id") or row.get(f"{side}_id") or "").strip()
            name = str(player.get("name") or row.get(f"{side}_name") or "").strip()
            key = pid or name.lower()
            if not key:
                continue
            explicit = str(player.get("photo_url") or player.get("image_url") or player.get("photo") or row.get(f"{side}_photo_url") or row.get(f"{side}_image_url") or "").strip()
            proxy_ref = bool(pid.isdigit())
            players[key] = bool(players.get(key) or explicit or proxy_ref)

        tournament = str(row.get("tournament") or row.get("competition_name") or row.get("competition") or "").strip()
        tid = str(row.get("tournament_logo_id") or row.get("tournament_id") or row.get("unique_tournament_id") or "").strip()
        tkey = tid or tournament.lower()
        if tkey:
            explicit_logo = str(row.get("tournament_logo_url") or row.get("competition_logo_url") or row.get("competition_logo") or row.get("tournament_logo") or "").strip()
            tournaments[tkey] = bool(tournaments.get(tkey) or explicit_logo or tid.isdigit())

    player_total = len(players)
    player_refs = sum(1 for ok in players.values() if ok)
    tournament_total = len(tournaments)
    tournament_refs = sum(1 for ok in tournaments.values() if ok)
    return {
        "player_images": {
            "total": player_total,
            "provider_or_proxy_refs": player_refs,
            "fallback_needed": max(0, player_total - player_refs),
            "ok": player_total == 0 or player_refs == player_total,
        },
        "tournament_logos": {
            "total": tournament_total,
            "provider_or_proxy_refs": tournament_refs,
            "fallback_needed": max(0, tournament_total - tournament_refs),
            "ok": tournament_total == 0 or tournament_refs == tournament_total,
        },
    }


@app.route(route="v1/admin/diagnostics", methods=["GET"])
def admin_diagnostics(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        storage = admin_storage_diagnostics()
        storage_ok = storage.get("backend") != "unavailable"
        media = media_storage_diagnostics()
        push = push_storage_diagnostics()
        try:
            runtime_ui = load_runtime_ui_config() or {}
        except AdminStorageUnavailable:
            runtime_ui = {}
        inactivity = inactivity_policy(runtime_ui)
        smtp = smtp_diagnostics(settings)
        account_worker_configured = bool(str(getattr(settings, "blinq_account_worker_token", "") or "").strip())
        try:
            account_worker_status = load_account_worker_status() or {}
        except AdminStorageUnavailable:
            account_worker_status = {}
        account_worker_age_seconds = None
        account_worker_healthy = False
        raw_account_worker_time = str(account_worker_status.get("updated_at") or account_worker_status.get("scanned_at") or "").strip()
        if raw_account_worker_time:
            try:
                account_worker_moment = datetime.fromisoformat(raw_account_worker_time.replace("Z", "+00:00"))
                if account_worker_moment.tzinfo is None: account_worker_moment = account_worker_moment.replace(tzinfo=timezone.utc)
                account_worker_age_seconds = max(0, int((datetime.now(timezone.utc)-account_worker_moment.astimezone(timezone.utc)).total_seconds()))
                account_worker_healthy = bool(account_worker_configured and account_worker_age_seconds <= 36*3600 and not account_worker_status.get("last_error"))
            except ValueError:
                pass
        worker_configured = bool(str(os.getenv("BLINQ_LIVE_WORKER_TOKEN") or "").strip())
        try:
            worker_status = load_live_worker_status() or {}
        except AdminStorageUnavailable:
            worker_status = {}
        worker_age_seconds = None
        worker_healthy = False
        raw_worker_time = str(worker_status.get("updated_at") or worker_status.get("scanned_at") or "").strip()
        if raw_worker_time:
            try:
                worker_moment = datetime.fromisoformat(raw_worker_time.replace("Z", "+00:00"))
                if worker_moment.tzinfo is None: worker_moment = worker_moment.replace(tzinfo=timezone.utc)
                worker_age_seconds = max(0, int((datetime.now(timezone.utc)-worker_moment.astimezone(timezone.utc)).total_seconds()))
                worker_healthy = bool(worker_configured and worker_age_seconds <= 180 and not worker_status.get("last_error"))
            except ValueError:
                pass
        feed_health = {"ready": False, "stale": True, "generated_at": None, "upcoming": 0, "results": 0, "model_version": None}
        try:
            raw_feed = read_feed(FEED)
            visible = visible_feed(raw_feed)
            model = raw_feed.get("model") or {}
            feed_health = {
                "ready": bool(raw_feed.get("ready") or raw_feed.get("generated_at") or raw_feed.get("upcoming") or raw_feed.get("results")),
                "stale": bool(visible.get("stale", True)),
                "generated_at": raw_feed.get("generated_at"),
                "upcoming": len(raw_feed.get("upcoming") or []),
                "results": len(raw_feed.get("results") or []),
                "model_version": model.get("version") if isinstance(model, dict) else None,
            }
        except Exception as exc:
            feed_health["error"] = exc.__class__.__name__
        asset_health = _feed_asset_health(raw_feed if 'raw_feed' in locals() else {})
        storage_services = storage.get("services") or {}
        service_health = {
            "info_storage": bool(storage_services.get("premium_info")),
            "live_data": bool(feed_health.get("ready") and not feed_health.get("stale")),
            "live_worker": bool(worker_healthy),
        }
        provider_health = {
            "configured": bool(str(getattr(settings, "rapidapi_key", "") or "").strip()),
            "host": str(getattr(settings, "rapidapi_host", "") or "")[:120],
        }
        users_ok = False
        try:
            list_users(settings, page=1, per_page=1)
            users_ok = True
        except Exception:
            users_ok = False
        firebase_server_configured = bool(
            str(getattr(settings, "firebase_project_id", "") or "").strip()
            and str(getattr(settings, "firebase_client_email", "") or "").strip()
            and str(getattr(settings, "firebase_private_key", "") or "").strip()
        )
        try:
            ops = list_system_events(hours=24, limit=50)
        except AdminStorageUnavailable:
            ops = {"hours": 24, "counts": {"info": 0, "warning": 0, "error": 0}, "items": [], "available": False}
        problems = []
        if not firebase_server_configured:
            problems.append("firebase_admin_credentials_missing")
        elif not users_ok:
            problems.append("firebase_admin_users_unavailable")
        if not storage_ok:
            problems.append("admin_storage_unavailable")
        if not media.get("configured") or not media.get("available"):
            problems.append("media_storage_unavailable")
        if not worker_configured:
            problems.append("live_worker_token_missing")
        elif not worker_healthy:
            problems.append("live_worker_stale")
        if inactivity.get("enabled"):
            if not account_worker_configured:
                problems.append("account_worker_token_missing")
            elif not account_worker_healthy:
                problems.append("account_worker_stale")
            if (inactivity.get("notify_admin") or inactivity.get("notify_user") or inactivity.get("auto_expire_rookie")) and not smtp.get("configured"):
                problems.append("smtp_not_configured")
            if inactivity.get("notify_admin") and not smtp.get("admin_recipient_configured"):
                problems.append("admin_email_missing")
        if not push.get("enabled"):
            problems.append("webpush_not_configured")
        elif not push.get("storage_available"):
            problems.append("webpush_storage_unavailable")
        return response({
            "ok": bool(users_ok),
            "accounts_ready": bool(users_ok),
            "content_storage_ready": bool(storage_ok),
            "release": RELEASE,
            "media_storage": media,
            "webpush": push,
            "live_worker": {
                "configured": worker_configured,
                "healthy": worker_healthy,
                "age_seconds": worker_age_seconds,
                "scanned_at": worker_status.get("scanned_at"),
                "live_events": int(worker_status.get("live_events") or 0),
                "candidates": int(worker_status.get("candidates") or 0),
                "signals": int(worker_status.get("signals") or 0),
                "new_alerts": int(worker_status.get("new_alerts") or 0),
                "last_error": str(worker_status.get("last_error") or "")[:160],
            },
            "account_inactivity": {
                "policy": inactivity,
                "worker": {
                    "configured": account_worker_configured,
                    "healthy": account_worker_healthy,
                    "age_seconds": account_worker_age_seconds,
                    "scanned_at": account_worker_status.get("scanned_at"),
                    "scanned": int(account_worker_status.get("scanned") or 0),
                    "inactive": int(account_worker_status.get("inactive") or 0),
                    "warnings": int(account_worker_status.get("warnings") or 0),
                    "expired": int(account_worker_status.get("expired") or 0),
                    "last_error": str(account_worker_status.get("last_error") or "")[:160],
                },
                "smtp": smtp,
            },
            "auth_provider": auth_provider(settings),
            "admin_storage": storage.get("backend"),
            "storage": storage,
            "firebase_server_configured": firebase_server_configured,
            "firebase_admin_users": users_ok,
            "feed": feed_health,
            "assets": asset_health,
            "services": service_health,
            "provider": provider_health,
            "ops": ops,
            "problems": problems,
            "actor_id": actor.get("id"),
            "checked_at": time.time(),
        }, 200)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)

@app.route(route="v1/admin/users", methods=["GET"])
def admin_users(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        try:
            page = max(1, int(req.params.get("page") or 1))
            per_page = max(1, min(200, int(req.params.get("per_page") or 100)))
        except (TypeError, ValueError):
            return response({"error": "invalid_pagination"}, 400)
        users = list_users(settings, page=page, per_page=per_page)
        storage_warning = None
        try:
            profiles = load_account_metadata_many([user.get("id") for user in users])
        except AdminStorageUnavailable:
            profiles = {str(user.get("id") or ""): profile_claims(user) for user in users}
            storage_warning = "operational_metadata_fallback"
        payload = {
            "users": [_admin_account_row(user, profiles.get(str(user.get("id") or ""), {})) for user in users],
            "page": page,
            "per_page": per_page,
            "actor_id": actor.get("id"),
        }
        if storage_warning:
            payload["storage_warning"] = storage_warning
        return response(payload)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except (ValueError, TypeError):
        logging.exception("Admin user listing failed")
        return response({"error": "admin_users_unavailable"}, 503)


@app.route(route="v1/admin/users/{user_id}/access", methods=["PUT"])
def admin_user_access(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        user_id = str((req.route_params or {}).get("user_id") or "").strip()
        if not user_id:
            return response({"error": "invalid_user_id"}, 400)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if user_id == str(actor.get("id")):
            requested_role = str((payload or {}).get("role") or "user").strip().lower()
            requested_status = str((payload or {}).get("status") or "expired").strip().lower()
            if requested_role != "admin" or requested_status == "suspended":
                return response({"error": "cannot_disable_own_admin_access"}, 409)
        updated = update_user_access(
            settings,
            user_id,
            payload,
            actor_id=str(actor.get("id") or ""),
        )
        updated_row = _admin_account_row(updated)
        sync_push_access(
            user_id=user_id,
            plan=str(updated_row.get("plan") or ""),
            status=str(updated_row.get("status") or ""),
            expires_at=updated_row.get("expires_at"),
        )
        return response(updated_row)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except (TypeError, KeyError):
        logging.exception("Admin access update failed")
        return response({"error": "admin_update_unavailable"}, 503)

@app.route(route="v1/admin/users/{user_id}/profile", methods=["PUT"])
def admin_user_profile(req):
    """Let an admin correct the small set of user-owned account fields.

    This intentionally stays separate from level/expiry management.
    """
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        user_id = str((req.route_params or {}).get("user_id") or "").strip()
        if not user_id:
            return response({"error": "invalid_user_id"}, 400)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return response({"error": "invalid_profile_update"}, 400)

        identity_payload = {key: payload[key] for key in ("email", "display_name") if key in payload}
        profile_payload = {key: payload[key] for key in ("telegram_nick", "display_name") if key in payload}
        if not identity_payload and not profile_payload:
            return response({"error": "empty_profile_update"}, 400)

        target = update_user_identity(settings, user_id, identity_payload) if identity_payload else get_user(settings, user_id)
        profile = _profile_for(target, required=False)
        storage_warning = None
        if profile_payload:
            normalized = normalize_profile_update(profile_payload)
            target = mirror_profile_claims(settings, user_id, profile_payload)
            try:
                profile = save_profile_metadata(user_id, profile_payload)
            except AdminStorageUnavailable:
                profile = {**profile_claims(target), **{k: normalized.get(k) for k in ("telegram_nick", "display_name") if k in normalized}}
                storage_warning = "profile_storage_fallback"
        row = _admin_account_row(target, profile)
        if storage_warning:
            row["storage_warning"] = storage_warning
        return response(row)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "account_storage_unavailable"}, 503)


@app.route(route="v1/admin/users/{user_id}", methods=["DELETE"])
def admin_user_delete(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        user_id = str((req.route_params or {}).get("user_id") or "").strip()
        if not user_id:
            return response({"error": "invalid_user_id"}, 400)
        if user_id == str(actor.get("id") or ""):
            return response({"error": "cannot_delete_own_admin_account"}, 409)
        # Delete identity first: an account that still authenticates is never
        # reported as deleted merely because optional metadata cleanup failed.
        delete_user_account(settings, user_id)
        storage_warning = None
        try:
            delete_account_metadata(user_id)
        except AdminStorageUnavailable:
            storage_warning = "profile_metadata_cleanup_pending"
        payload = {"ok": True, "deleted_user_id": user_id}
        if storage_warning:
            payload["storage_warning"] = storage_warning
        return response(payload)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)


@app.route(route="v1/admin/users/{user_id}/metadata", methods=["PUT"])
def admin_user_metadata(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        user_id = str((req.route_params or {}).get("user_id") or "").strip()
        if not user_id:
            return response({"error": "invalid_user_id"}, 400)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        normalized = normalize_admin_metadata_update(payload)
        target = get_user(settings, user_id)
        # TG Private is mirrored in a tiny Firebase claim so manual group
        # operations continue even if the optional metadata store is down.
        target = mirror_admin_metadata_claims(settings, user_id, normalized)
        storage_warning = None
        try:
            before = load_account_metadata(user_id)
            after = save_admin_metadata(user_id, normalized, actor_id=str(actor.get("id") or ""))
            try:
                record_admin_metadata_audit(
                    actor_id=str(actor.get("id") or ""),
                    target_id=user_id,
                    before=before,
                    after=after,
                )
            except AdminStorageUnavailable:
                logging.warning("Admin account metadata audit unavailable")
        except AdminStorageUnavailable:
            after = profile_claims(target)
            storage_warning = "admin_note_not_persisted" if "admin_note" in normalized else "operational_metadata_fallback"
        row = _admin_account_row(target, after)
        if storage_warning:
            row["storage_warning"] = storage_warning
        return response(row)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except (TypeError, KeyError):
        logging.exception("Admin metadata update failed")
        return response({"error": "admin_update_unavailable"}, 503)


@app.route(route="v1/admin/users/{user_id}/payments", methods=["GET", "POST"])
def admin_user_payments(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        user_id = str((req.route_params or {}).get("user_id") or "").strip()
        if not user_id:
            return response({"error": "invalid_user_id"}, 400)
        if req.method == "GET":
            return response({"items": list_manual_payments(user_id, limit=200)})
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        payment = record_manual_payment(user_id, payload, actor_id=str(actor.get("id") or ""))
        return response({"saved": True, "payment": payment, "items": list_manual_payments(user_id, limit=200)}, 201)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)


@app.route(route="v1/admin/audit", methods=["GET"])
def admin_audit(req):
    try:
        _, denied = _admin_user(req)
        if denied:
            return denied
        target_id = str(req.params.get("target_id") or "").strip()
        try:
            limit = int(req.params.get("limit") or 200)
        except (TypeError, ValueError):
            return response({"error": "invalid_limit"}, 400)
        return response({"items": list_account_audit(target_id=target_id, limit=limit)})
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)




@app.route(route="v1/admin/insights", methods=["GET", "POST"])
def admin_insights(req):
    try:
        admin, failure = _admin_user(req)
        if failure:
            return failure
        if req.method == "GET":
            return response(list_insights(include_inactive=True, limit=250))
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        return response(save_insight(payload, actor_id=str(admin.get("id") or "")), 201)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/admin/insights/{insight_id}", methods=["PUT", "DELETE"])
def admin_insight_item(req):
    try:
        admin, failure = _admin_user(req)
        if failure:
            return failure
        insight_id = str((req.route_params or {}).get("insight_id") or "")
        if req.method == "DELETE":
            return response(delete_insight(insight_id))
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        return response(save_insight(payload, actor_id=str(admin.get("id") or ""), insight_id=insight_id))
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)

@app.route(route="v1/admin/ui-config", methods=["PUT"])
def admin_ui_config(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        saved = save_runtime_ui_config(payload, actor_id=str(actor.get("id") or ""))
        return response(saved)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)


@app.route(route="v1/admin/media", methods=["POST"])
def admin_media_upload(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        content_type = str(req.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        filename = str(req.headers.get("X-Blinq-Filename") or "")[:240]
        data = req.get_body() or b""
        return response(upload_media(
            data,
            content_type=content_type,
            original_name=filename,
            actor_id=str(actor.get("id") or ""),
        ), 201)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except MediaStorageUnavailable:
        return response({"error": "media_storage_unavailable"}, 503)


@app.route(route="v1/admin/banner-analytics", methods=["GET"])
def admin_banner_analytics(req):
    try:
        _, denied = _admin_user(req)
        if denied:
            return denied
        try:
            days = int(req.params.get("days") or 30)
        except (TypeError, ValueError):
            return response({"error": "invalid_days"}, 400)
        return response(banner_analytics_summary(days=days))
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"available": False, "error": "admin_storage_unavailable"}, 503)

