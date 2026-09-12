"""Server-owned BlinQ membership entitlements.

Runtime admin configuration may only *narrow* the hard server policy.  This
keeps the browser from becoming the authorization source while still allowing
an administrator to choose how many rows each membership level may receive.
"""
from __future__ import annotations

from copy import deepcopy


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
        "daily": (1, False), "prime": (1, False), "top_daily": (0, False), "value": (0, False),
        "doubles": (1, False), "ace": (0, False), "sg": (0, False),
    },
    "rookie": {
        "daily": (5, False), "prime": (3, False), "top_daily": (2, False), "value": (1, False),
        "doubles": (1, False), "ace": (1, False), "sg": (1, False),
    },
    "pro": {
        "daily": (10, True), "prime": (5, True), "top_daily": (5, True), "value": (5, True),
        "doubles": (5, True), "ace": (5, True), "sg": (5, True),
    },
    "elite": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
    "legend": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
    "goat": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
    "admin": {key: ("ALL", True) for key in ["daily", *SECTION_TO_FEED_KEY]},
}


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
    value_ids={_row_id(row) for row in payload.get("value_picks", []) if isinstance(row, dict)}
    out=[]; seen=set()
    for key in ("prime_picks", "top_daily_picks"):
        for row in payload.get(key, []) if isinstance(payload.get(key), list) else []:
            if not isinstance(row, dict): continue
            ident=_row_id(row)
            if ident in seen or ident in value_ids: continue
            odds=_row_odds(row)
            if odds is None or odds < 1.45: continue
            seen.add(ident); out.append(row)
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


def entitlement_manifest(access: dict, payload: dict | None = None, ui_config: dict | None = None) -> dict:
    plan = effective_plan(access)
    if plan == "suspended":
        return {"plan": plan, "sections": {}, "results": False, "performance": False}
    policy = _POLICY.get(plan, _POLICY["expired"])
    payload = payload or {}
    sections = {}
    source_map={"daily":_daily_rows(payload), **{section:(payload.get(feed_key) if isinstance(payload.get(feed_key),list) else []) for section,feed_key in SECTION_TO_FEED_KEY.items()}}
    tab_map={"daily":"daily","value":"value","ace":"ace","sg":"games"}
    for section, rows in source_map.items():
        hard_limit, hard_see_all = policy.get(section, (0,False))
        runtime_rule=_admin_hub_rule(ui_config, tab_map[section], plan) if section in tab_map else None
        runtime_limit=runtime_rule[0] if runtime_rule else None
        limit=_narrow_limit(hard_limit,runtime_limit)
        returned=len(rows) if str(limit).upper()=="ALL" else min(len(rows),max(0,int(limit)))
        blur=runtime_rule[1] if runtime_rule else (str(limit).upper()!="ALL" and returned<len(rows))
        see_all=(runtime_rule[2] if runtime_rule else hard_see_all) and hard_see_all
        enabled=(runtime_rule[3] if runtime_rule else True)
        sections[section]={"visible_picks":limit,"see_all":bool(see_all),"blur_remaining":bool(blur),"enabled":bool(enabled),"total":len(rows),"returned":returned,"locked_count":max(0,len(rows)-returned)}
    return {"plan":plan,"sections":sections,"results":True,"performance":True}


def filter_feed_for_access(payload: dict, access: dict, ui_config: dict | None = None) -> tuple[dict, dict]:
    if not isinstance(payload, dict): raise ValueError("Invalid serving feed root")
    manifest=entitlement_manifest(access,payload,ui_config)
    if manifest["plan"]=="suspended": raise PermissionError("account_suspended")
    result=deepcopy(payload)

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
