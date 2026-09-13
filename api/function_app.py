from pathlib import Path
from collections import defaultdict, deque
from threading import Lock
import hashlib
import logging
import json
import time

import azure.functions as func

from tbt.config import settings
from tbt.services.auth import (
    AuthUnavailable,
    auth_provider,
    is_admin,
    is_suspended,
    public_account,
    request_authorization,
    update_firebase_profile,
    verify_user,
)
from tbt.services.admin_accounts import list_users, update_user_access
from tbt.services.account_storage import (
    load_account_metadata,
    load_account_metadata_many,
    normalize_profile_update,
    save_profile_metadata,
)
from tbt.services.admin_storage import (
    AdminStorageUnavailable,
    banner_analytics_summary,
    load_runtime_ui_config,
    record_banner_event,
    save_runtime_ui_config,
)
from tbt.services.content_news import news_pool
from tbt.services.feed import read_feed, visible_feed
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.entitlements import filter_feed_for_access

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
FEED = Path(__file__).parent / "data/feed.json"
RELEASE = "6.6.4"
API_VERSION = "3.5.1"

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
    try:
        return load_account_metadata(user.get("id"))
    except AdminStorageUnavailable:
        if required:
            raise
        logging.exception("Account metadata storage unavailable")
        return {}


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
    profile = profile if isinstance(profile, dict) else _profile_for(user, required=True)
    account = public_account(user, cfg=settings, profile=profile)
    return {
        **account,
        "created_at": user.get("created_at"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "payment_reference": str(profile.get("payment_reference") or "")[:120],
    }


@app.route(route="health", methods=["GET"])
def health(req):
    return response({"ok": True, "version": API_VERSION, "release": RELEASE, "auth": auth_provider(settings)})


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
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        if auth_provider(settings) != "firebase":
            return response({"error": "profile_update_unavailable"}, 503)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        normalized = normalize_profile_update(payload)
        firebase_payload = {}
        if isinstance(payload, dict) and "display_name" in payload:
            firebase_payload["display_name"] = normalized["display_name"]
        updated = update_firebase_profile(settings, user.get("id"), firebase_payload)
        profile = save_profile_metadata(user.get("id"), payload)
        return response(public_account(updated, cfg=settings, profile=profile))
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
        logging.exception("Match intelligence enrichment failed")
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
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except (ValueError, OSError, KeyError, TypeError):
        logging.exception("Serving feed unavailable")
        return response({"error": "feed_unavailable"}, 503)


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
        profiles = load_account_metadata_many([user.get("id") for user in users])
        return response({
            "users": [_admin_account_row(user, profiles.get(str(user.get("id") or ""), {})) for user in users],
            "page": page,
            "per_page": per_page,
            "actor_id": actor.get("id"),
        })
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
        return response(_admin_account_row(updated))
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except (TypeError, KeyError):
        logging.exception("Admin access update failed")
        return response({"error": "admin_update_unavailable"}, 503)

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

