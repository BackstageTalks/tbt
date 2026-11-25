"""Admin 'Ponuka' switches that shape the published offer (pick selection).

Stored in the admin UI table (one entity per key, with actor + timestamp).
The data pipeline reads them through an internal worker endpoint and exports
them as environment variables before scripts/pipeline.py runs. A missing or
unreachable store never changes the offer: GitHub repo Variables stay the
fallback, exactly as before this module existed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .admin_storage import _table, UI_TABLE, AdminStorageUnavailable

PARTITION = "offer-flags-v1"

# key, type, label, help, default, (min, max) for numbers
FLAGS: list[dict] = [
    {"key": "TBT_VALUE_SERVE_RETURN", "type": "bool", "group": "Value",
     "label": "Value: podanie + príjem",
     "help": "Value len na stranu s lepšou formou podania a príjmu (min. rozdiel nižšie).",
     "default": True},
    {"key": "TBT_VALUE_SERVE_RETURN_MIN", "type": "number", "group": "Value",
     "label": "Value: min. rozdiel podanie+príjem", "help": "Odporúčané 0,06.",
     "default": 0.06, "min": 0.0, "max": 0.3, "step": 0.01},
    {"key": "TBT_VALUE_LEVELS", "type": "choice_multi", "group": "Value",
     "label": "Value: súťaže",
     "help": "Kde sa Value ponúka. Backtest 2022-26: ITF muži +4,7 % ROI, ATP +4,8 %; Challenger, ITF ženy, WTA 125 stratové.",
     "default": "ATP,ITF-M",
     "options": ["ATP", "WTA", "Challenger", "WTA 125", "ITF-M", "ITF-W"]},
    {"key": "TBT_TOP_LOW_ODDS_FILL", "type": "number", "group": "TOP",
     "label": "TOP: doplnenie kurzom od",
     "help": "Ak je málo TOP tipov s kurzom ≥1,50, doplní tipy od tohto kurzu (napr. 1,40). 0 = vypnuté. Trh: 1,40-1,50 vyhrá ~70 %.",
     "default": 1.40, "min": 0.0, "max": 1.49, "step": 0.05},
    {"key": "TBT_TOP_MIN_PICKS", "type": "number", "group": "TOP",
     "label": "TOP: minimum predikcií", "help": "Prázdne/0 = predvolené.",
     "default": 0, "min": 0, "max": 10, "step": 1},
    {"key": "TBT_TOP_REQUIRE_MARKET_SIDE", "type": "bool", "group": "TOP",
     "label": "TOP: len favorit trhu", "help": "TOP len ak model aj trh vyberajú rovnakú stranu.",
     "default": False},
    {"key": "TBT_ACES_CUSHION_RULE", "type": "bool", "group": "Esá",
     "label": "Esá: pravidlo rezervy 1,5", "help": "Over/Under len s rezervou ≥1,5 esa voči reálnej línii.",
     "default": False},
    {"key": "TBT_ACES_MIN_GAP", "type": "number", "group": "Esá",
     "label": "Esá: preferovaný rozdiel", "help": "0 = predvolené.",
     "default": 0.0, "min": 0.0, "max": 5.0, "step": 0.5},
    {"key": "TBT_GAMES_SUSPENDED", "type": "bool", "group": "Gemy / Sety",
     "label": "Gemy: pozastaviť", "help": "Dočasne nepublikovať predikcie na gemy. Pozastavené od 24.11. (úspešnosť 49,5 %).", "default": True},
    {"key": "TBT_SETS_SUSPENDED", "type": "bool", "group": "Gemy / Sety",
     "label": "Sety: pozastaviť", "help": "Dočasne nepublikovať predikcie na sety. Pozastavené od 24.11. (pod základnou mierou).", "default": True},
    {"key": "TBT_RANK_SOURCE", "type": "bool", "group": "TOP",
     "label": "TOP: poradie podľa trhu (market-anchored)",
     "help": "Zapnuté = poradie TOP kombinuje model a trh. Vypnuté = čistý model (predvolené).",
     "default": False, "env_true": "market_anchored", "env_false": "model"},
    {"key": "TBT_TOP_MAX_MARKET_GAP", "type": "number", "group": "TOP",
     "label": "TOP: max. rozdiel model − trh", "min": 0, "max": 0.5, "step": 0.01,
     "help": "TOP len ak model neverí o viac než toto ako kurz (napr. 0,15). 0 = vypnuté. Audit 25.11.: nad 0,15 vyhralo 43 %.", "default": 0},
    {"key": "TBT_TOP_EMERGENCY_FILL", "type": "bool", "group": "TOP",
     "label": "TOP: núdzové doplnenie",
     "help": "Ak ani po doplnení od 1,40 nie je dosť TOP tipov, doplní najlepšie zostávajúce.",
     "default": False},
    {"key": "TBT_ACES_REAL_LINE_STRICT", "type": "bool", "group": "Esá",
     "label": "Esá: len reálne hranice",
     "help": "Esá len s hranicou od bookmakera; bez nej sa zápas neponúkne.", "default": False},
    {"key": "TBT_OFFER_SHADOW_DISABLED", "type": "bool", "group": "Shadow testing",
     "label": "Shadow testing: vypnúť",
     "help": "Zastaví zber virtuálnych (nepublikovaných) predikcií.", "default": False},
]
BY_KEY = {f["key"]: f for f in FLAGS}


def _validate(key: str, value):
    spec = BY_KEY.get(key)
    if spec is None:
        raise ValueError("unknown_offer_flag")
    kind = spec["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("invalid_bool")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid_number")
        if not spec["min"] <= float(value) <= spec["max"]:
            raise ValueError("number_out_of_range")
        return float(value)
    if kind == "choice_multi":
        items = [v.strip() for v in str(value).split(",") if v.strip()]
        if any(v not in spec["options"] for v in items) or len(set(items)) != len(items):
            raise ValueError("invalid_choice")
        return ",".join(items)
    raise ValueError("unsupported_flag_type")


def load_offer_flags() -> dict:
    """Return {key: {value, updated_at, actor_id}} for keys saved in admin."""
    try:
        table = _table(UI_TABLE)
        out = {}
        for e in table.query_entities(f"PartitionKey eq '{PARTITION}'"):
            key = str(e.get("RowKey") or "")
            if key in BY_KEY and "value_json" in e:
                import json
                out[key] = {"value": json.loads(e["value_json"]),
                            "updated_at": e.get("updated_at"), "actor_id": e.get("actor_id")}
        return out
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to read offer flags") from exc


def set_offer_flags(updates: dict, actor_id: str) -> dict:
    import json
    if not isinstance(updates, dict) or not 1 <= len(updates) <= len(FLAGS) or not actor_id:
        raise ValueError("invalid_offer_flags_request")
    clean = {k: _validate(k, v) for k, v in updates.items()}
    now = datetime.now(timezone.utc).isoformat()
    try:
        table = _table(UI_TABLE)
        for key, value in clean.items():
            table.upsert_entity({"PartitionKey": PARTITION, "RowKey": key,
                                 "value_json": json.dumps(value), "actor_id": str(actor_id)[:100],
                                 "updated_at": now}, mode="replace")
        persisted = load_offer_flags()
        if any(persisted.get(k, {}).get("value") != v for k, v in clean.items()):
            raise AdminStorageUnavailable("Offer flag readback mismatch")
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to update offer flags") from exc
    return {"updated": sorted(clean), "flags": persisted}


def describe() -> dict:
    saved = load_offer_flags()
    items = []
    for spec in FLAGS:
        row = dict(spec)
        if spec["key"] in saved:
            row.update(value=saved[spec["key"]]["value"], saved=True,
                       updated_at=saved[spec["key"]]["updated_at"], actor_id=saved[spec["key"]]["actor_id"])
        else:
            row.update(value=spec["default"], saved=False)
        items.append(row)
    return {"items": items}


def as_env(saved: dict) -> dict[str, str]:
    """Only admin-saved keys; unsaved keys keep the GitHub Variable fallback."""
    env = {}
    for key, row in saved.items():
        v = row.get("value")
        spec = BY_KEY.get(key, {})
        if isinstance(v, bool) and "env_true" in spec:
            env[key] = spec["env_true"] if v else spec["env_false"]
        elif isinstance(v, bool):
            env[key] = "true" if v else "false"
        elif isinstance(v, float):
            env[key] = "" if v == 0 else f"{v:g}"
        else:
            env[key] = str(v)
    return env
