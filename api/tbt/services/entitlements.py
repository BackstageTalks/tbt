"""Server-owned BlinQ membership entitlements.

Runtime admin configuration controls the visible row count inside a hard
server-side cap.  Repository defaults remain conservative when runtime storage
is unavailable, while published admin rules may explicitly set 0..10 rows.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone


SECTION_TO_FEED_KEY = {
    "prime": "prime_picks",
    "top_daily": "top_daily_picks",
    "value": "value_picks",
    "doubles": "doubles_picks",
    "ace": "ace_picks",
    "sg": "sg_picks",
}

_POLICY = {
    "expired": {
        "daily": (0, False), "prime": (0, False), "top_daily": (0, False), "value": (0, False),
        "doubles": (0, False), "ace": (0, False), "sg": (0, False),
    },
    "rookie": {
        "daily": (1, False), "prime": (1, False), "top_daily": (1, False), "value": (1, False),
        "doubles": (0, False), "ace": (0, False), "sg": (0, False),
    },
    "pro": {
        "daily": (3, False), "prime": (3, False), "top_daily": (3, False), "value": (3, False),
        "doubles": (0, False), "ace": (0, False), "sg": (0, False),
    },
    "elite": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
    "legend": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
    "goat": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
    "admin": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
}

# Admin may explicitly configure 0..10 visible picks for every category.  The
# server remains the authorization boundary: runtime values are capped here.
_RUNTIME_PICK_CAP = 10

# BlinQ Board is an advanced, non-public model workspace. It is intentionally
# independent of bookmaker price: rows qualify on model confidence and evidence
# quality only, then expose odds merely as optional context when a snapshot exists.
BOARD_MIN_PROBABILITY = 0.65
BOARD_MIN_DATA_DEPTH = 0.80
BOARD_MIN_SURFACE_MATCHES = 5
BOARD_PLANS = {"legend", "goat", "admin"}

RESULT_HISTORY_HOURS = {
    "rookie": 24,
    "pro": 48,
    "elite": None,
    "legend": None,
    "goat": None,
    "admin": None,
    "expired": 0,
}


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _result_timestamp(row: dict) -> datetime | None:
    for key in ("scheduled_at", "date", "start_time", "start_at", "settled_at"):
        dt = _parse_datetime(row.get(key))
        if dt is not None:
            return dt
    return None


def _filter_result_history(rows: list, hours: int | None, now: datetime | None = None) -> list:
    if hours is None:
        return deepcopy(rows)
    if hours <= 0:
        return []
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _result_timestamp(row)
        if ts is not None and cutoff <= ts <= now + timedelta(hours=6):
            out.append(deepcopy(row))
    return out



def effective_plan(access: dict) -> str:
    if bool(access.get("is_admin")) or str(access.get("role") or "").lower() == "admin":
        return "admin"
    status = str(access.get("status") or "").lower()
    plan = str(access.get("plan") or "").lower()
    if status == "suspended":
        return "suspended"
    if status == "trial":
        return "rookie"
    if status in {"active", "lifetime"} and plan in {"rookie", "pro", "elite", "legend", "goat"}:
        return plan
    return "expired"


def _row_id(row: dict) -> tuple[str, str]:
    return (str(row.get("event_id") or row.get("id") or ""), str(row.get("pick") or row.get("selection") or row.get("prediction") or ""))


def _row_probability(row: dict) -> float:
    for key in ("blinq_probability", "probability", "win_probability", "model_probability", "confidence_probability"):
        try:
            value = float(row.get(key))
            return value / 100 if value > 1 else value
        except (TypeError, ValueError):
            continue
    players = [row.get("player1") or {}, row.get("player2") or {}]
    vals=[]
    for player in players:
        try: vals.append(float(player.get("probability")))
        except (TypeError, ValueError): pass
    return max(vals) if vals else 0.0


def _row_odds(row: dict) -> float | None:
    candidates = [row.get("odds"), (row.get("betting") or {}).get("odds")]
    for candidate in candidates:
        try:
            value=float(candidate)
            if value > 1: return value
        except (TypeError, ValueError):
            pass
    return None


def _daily_rows(payload: dict) -> list[dict]:
    """Build the public TOP board.

    VALUE has priority over TOP, so any row already qualifying for VALUE is
    removed from the TOP board. PRIME is intentionally *not* merged here:
    PRIME is an internal pool reserved for the Comeback LIVE Radar and must not
    leak back into the public TOP category.
    """
    value_ids={_row_id(row) for row in payload.get("value_picks", []) if isinstance(row, dict)}
    out=[]; seen=set()
    rows = payload.get("top_daily_picks", []) if isinstance(payload.get("top_daily_picks"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident=_row_id(row)
        if ident in seen or ident in value_ids:
            continue
        odds=_row_odds(row)
        if odds is None or odds < 1.45:
            continue
        seen.add(ident)
        out.append(row)
    out.sort(key=lambda row: (-_row_probability(row), str(row.get("scheduled_at") or row.get("date") or "")))
    return out


def _admin_hub_rule(ui_config: dict | None, tab: str, plan: str) -> tuple[object, bool, bool, bool] | None:
    if not isinstance(ui_config, dict): return None
    hub=((ui_config.get("dashboard") or {}).get("daily_hub") or {})
    if hub.get("enabled") is False: return (0, True, False, False)
    cfg=((hub.get("tabs") or {}).get(tab) or {})
    if cfg.get("enabled") is False: return (0, True, False, False)
    plans=cfg.get("plans") or {}
    row=plans.get(plan) or plans.get("rookie")
    if not isinstance(row, dict): return None
    if row.get("tab_enabled") is False: return (0, True, False, False)
    visible=row.get("visible_rows", "ALL")
    blur=bool(row.get("blur_remaining", True))
    see_all=bool(row.get("see_all", False))
    return visible, blur, see_all, True


def _narrow_limit(hard: object, runtime: object) -> object:
    if runtime is None: return hard
    if str(hard).upper()=="ALL": return runtime
    if str(runtime).upper()=="ALL": return hard
    try: return min(max(0,int(hard)), max(0,int(runtime)))
    except (TypeError, ValueError): return hard


def _limit_rows(rows: list, limit: object) -> list:
    if str(limit).upper()=="ALL": return deepcopy(rows)
    try: n=max(0,int(limit))
    except (TypeError, ValueError): n=0
    return deepcopy(rows[:n])


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _board_probability(row: dict) -> float:
    for value in (
        row.get("blinq_probability"),
        (row.get("betting") or {}).get("blinq_probability") if isinstance(row.get("betting"), dict) else None,
        row.get("confidence"),
        row.get("raw_model_confidence"),
    ):
        number = _number(value)
        if number is not None:
            return number / 100.0 if number > 1 else number
    values = []
    for key in ("player1", "player2"):
        player = row.get(key) if isinstance(row.get(key), dict) else {}
        number = _number(player.get("probability"))
        if number is not None:
            values.append(number / 100.0 if number > 1 else number)
    return max(values, default=0.0)


def _board_surface_samples(row: dict) -> tuple[int, int]:
    quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
    counts = []
    for key in ("player1", "player2"):
        player = quality.get(key) if isinstance(quality.get(key), dict) else {}
        number = _number(player.get("surface_matches"))
        counts.append(max(0, int(number or 0)))
    return counts[0], counts[1]


def _board_row_eligible(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    surface = str(row.get("surface") or row.get("court_surface") or "").strip().lower()
    if not surface or surface == "unknown":
        return False
    depth = _number(row.get("data_depth"))
    if depth is None:
        depth = _number(row.get("probability_reliability"))
    p1_surface, p2_surface = _board_surface_samples(row)
    return (
        _board_probability(row) >= BOARD_MIN_PROBABILITY
        and (depth or 0.0) >= BOARD_MIN_DATA_DEPTH
        and p1_surface >= BOARD_MIN_SURFACE_MATCHES
        and p2_surface >= BOARD_MIN_SURFACE_MATCHES
    )


def _board_rows(payload: dict, key: str) -> list[dict]:
    rows = payload.get(key) if isinstance(payload.get(key), list) else []
    eligible = [row for row in rows if _board_row_eligible(row)]
    return sorted(
        eligible,
        key=lambda row: (-_board_probability(row), str(row.get("scheduled_at") or row.get("date") or "")),
    )


def entitlement_manifest(access: dict, payload: dict | None = None, ui_config: dict | None = None) -> dict:
    plan = effective_plan(access)
    if plan == "suspended":
        return {"plan": plan, "sections": {}, "results": False, "performance": False, "results_history_hours": 0}
    policy = _POLICY.get(plan, _POLICY["expired"])
    payload = payload or {}
    sections = {}
    source_map={"daily":_daily_rows(payload), **{section:(payload.get(feed_key) if isinstance(payload.get(feed_key),list) else []) for section,feed_key in SECTION_TO_FEED_KEY.items()}}
    tab_map={"daily":"daily","prime":"top","top_daily":"daily","value":"value","doubles":"doubles","ace":"ace","sg":"games"}
    for section, rows in source_map.items():
        default_limit, hard_see_all = policy.get(section, (0,False))
        runtime_rule=_admin_hub_rule(ui_config, tab_map[section], plan) if section in tab_map else None
        if runtime_rule:
            runtime_limit=runtime_rule[0]
            hard_cap="ALL" if plan in {"elite","legend","goat","admin"} else _RUNTIME_PICK_CAP
            limit=_narrow_limit(hard_cap,runtime_limit)
        else:
            limit=default_limit
        returned=len(rows) if str(limit).upper()=="ALL" else min(len(rows),max(0,int(limit)))
        blur=runtime_rule[1] if runtime_rule else (str(limit).upper()!="ALL" and returned<len(rows))
        see_all=(runtime_rule[2] if runtime_rule else hard_see_all) and hard_see_all
        enabled=(runtime_rule[3] if runtime_rule else True)
        sections[section]={"visible_picks":limit,"see_all":bool(see_all),"blur_remaining":bool(blur),"enabled":bool(enabled),"total":len(rows),"returned":returned,"locked_count":max(0,len(rows)-returned)}
    board_rows = _board_rows(payload, "upcoming")
    board_enabled = plan in BOARD_PLANS
    runtime_board = None if plan == "admin" else _admin_hub_rule(ui_config, "board", plan)
    if runtime_board is not None:
        board_enabled = board_enabled and bool(runtime_board[3])
    sections["board"] = {
        "visible_picks": "ALL" if board_enabled else 0,
        "see_all": bool(board_enabled),
        "blur_remaining": False,
        "enabled": bool(board_enabled),
        "total": len(board_rows) if board_enabled else 0,
        "returned": len(board_rows) if board_enabled else 0,
        "locked_count": 0,
        "min_probability": BOARD_MIN_PROBABILITY,
        "min_data_depth": BOARD_MIN_DATA_DEPTH,
        "min_surface_matches_each": BOARD_MIN_SURFACE_MATCHES,
        "official_prediction": False,
    }
    history_hours = RESULT_HISTORY_HOURS.get(plan, 0)
    return {
        "plan": plan,
        "sections": sections,
        "results": history_hours != 0,
        "performance": history_hours is None,
        "results_history_hours": history_hours,
    }


def filter_feed_for_access(payload: dict, access: dict, ui_config: dict | None = None) -> tuple[dict, dict]:
    if not isinstance(payload, dict): raise ValueError("Invalid serving feed root")
    manifest=entitlement_manifest(access,payload,ui_config)
    if manifest["plan"]=="suspended": raise PermissionError("account_suspended")
    result=deepcopy(payload)

    # Results are a separate entitlement boundary. Low tiers never receive the
    # full historical array and therefore cannot recover it from the browser.
    history_hours = manifest.get("results_history_hours")
    source_results = payload.get("results") if isinstance(payload.get("results"), list) else []
    result["results"] = _filter_result_history(source_results, history_hours)
    if history_hours is not None:
        # Aggregate performance in the published feed may cover all time, so do not
        # expose it to ROOKIE/PRO. Their UI calculates metrics from the authorized
        # 24h/48h result slice instead.
        if "performance" in result:
            result["performance"] = {}
        if "betting_performance" in result:
            result["betting_performance"] = {}

    board_enabled = bool(manifest.get("sections", {}).get("board", {}).get("enabled"))
    result["board_upcoming"] = _board_rows(payload, "upcoming") if board_enabled else []
    result["board_results"] = _board_rows(payload, "results") if board_enabled else []
    result["board_meta"] = {
        "official_prediction": False,
        "min_probability": BOARD_MIN_PROBABILITY,
        "min_data_depth": BOARD_MIN_DATA_DEPTH,
        "min_surface_matches_each": BOARD_MIN_SURFACE_MATCHES,
    } if board_enabled else {"official_prediction": False, "locked": True}

    daily_all=_daily_rows(payload)
    daily_limit=manifest["sections"]["daily"]["visible_picks"]
    daily_allowed=_limit_rows(daily_all,daily_limit)
    result["daily_picks"]=daily_allowed
    # Legacy section arrays remain server-filtered by their original hard policy
    # for backward-compatible detail routes. The new dashboard consumes only
    # `daily_picks`, which has its own stricter consolidated authorization.
    for section in ("prime", "top_daily"):
        feed_key=SECTION_TO_FEED_KEY[section]
        rows=payload.get(feed_key) if isinstance(payload.get(feed_key),list) else []
        limit=manifest["sections"][section]["visible_picks"]
        result[feed_key]=_limit_rows(rows,limit)

    for section,feed_key in SECTION_TO_FEED_KEY.items():
        if section in {"prime","top_daily"}: continue
        rows=payload.get(feed_key)
        if not isinstance(rows,list): continue
        ent_key="sg" if section=="sg" else section
        limit=manifest["sections"][ent_key]["visible_picks"]
        result[feed_key]=_limit_rows(rows,limit)

    if manifest["plan"] not in {"elite","legend","goat","admin"}:
        permitted_ids={str(row.get("event_id") or "") for feed_key in ["daily_picks","value_picks","doubles_picks","ace_picks","sg_picks"] for row in result.get(feed_key,[]) if isinstance(row,dict)}
        safe=[]
        for row in payload.get("upcoming",[]):
            if not isinstance(row,dict) or str(row.get("event_id") or "") not in permitted_ids: continue
            copy=deepcopy(row)
            for key in ("winner_id","signals","quality","betting","model_version"): copy.pop(key,None)
            for player_key in ("player1","player2"):
                player=copy.get(player_key)
                if isinstance(player,dict): player.pop("probability",None)
            safe.append(copy)
        result["upcoming"]=safe
    return result,manifest
