"""Read-only market-only Match Winner research. No production selectors or writes.

The historical 1.102 / -0.009 coefficients are UNVERIFIED against point-in-time
data. Never treat these as a trained production model, or change any public card.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Iterable


def _prob(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) and 0 < v < 1 else None


def _utc(value):
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _clip(value):
    return max(.01, min(.99, value))


def _sigmoid(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1 + exp_z)


def load_shadow_params(path: str | Path) -> dict:
    conf = json.loads(Path(path).read_text(encoding="utf-8"))
    if (conf.get("schema") != 1
            or conf.get("mode") != "SHADOW_READ_ONLY_NEVER_PUBLISH"
            or conf.get("activation_approved") is not False
            or conf.get("production_model_modified") is not False):
        raise ValueError("Research-only authorization guard failed")
    cal = conf.get("calibrator") or {}
    a, b = cal.get("slope"), cal.get("intercept")
    if (any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) for v in (a, b)) or a <= 0):
        raise ValueError("Invalid unverified market-only calibrator")
    # The alternative is traceable research metadata, never an implicit switch.
    opener = conf.get("opener_fallback") or {}
    if (opener.get("slope") != 1.088
            or opener.get("intercept") != -.008
            or opener.get("claimed_fit_n") != 36972
            or opener.get("source_tour") != "ATP"
            or opener.get("source_field") != "opener"
            or opener.get("production_enabled") is not False
            or opener.get("wta_verified") is not False
            or opener.get("independent_fit_reproduced") is not False):
        raise ValueError("ATP opener research variant lost its frozen provenance")
    prospective = conf.get("prospective") or {}
    if (prospective.get("n_min_daily_shadow") != 5
            or prospective.get("daily_minimum_requires_all_observed_days") is not True):
        raise ValueError("A0 daily non-silence gate must remain enforced")
    selector = conf.get("selector_experiments") or {}
    if (selector.get("veto_market_outsider_fair_below") != .5
            or selector.get("market_min_fair") != .75
            or selector.get("gap_absolute_max") != .10):
        raise ValueError("Unexpected experimental selector thresholds")
    return conf


def calibrate_market_only(fair: float, params: dict, *, variant: str = "main") -> float:
    """Research only; ATP opener is explicit, never a silent fallback."""
    p = _prob(fair)
    if p is None:
        raise ValueError("Both sides' real no-vig market fair must be known")
    p = _clip(p)
    if variant == "main":
        cal = params["calibrator"]
    elif variant == "opener":
        cal = params["opener_fallback"]
        if cal.get("production_enabled") is not False:
            raise ValueError("Opener fallback must never activate serving")
    else:
        raise ValueError("Unknown market-only research calibration variant")
    return _clip(_sigmoid(cal["slope"] * math.log(p/(1-p)) + cal["intercept"]))


def time_evidence(card: dict) -> dict:
    bet = card.get("betting") if isinstance(card.get("betting"), dict) else {}
    start = _utc(card.get("scheduled_at"))
    capture = _utc(bet.get("captured_at"))
    issued = _utc(card.get("issued_at") or card.get("created_at"))
    valid = (start is not None and capture is not None and issued is not None
             and capture <= issued < start)
    return {"valid": bool(valid),
            "scheduled_at": start.isoformat() if start else None,
            "captured_at": capture.isoformat() if capture else None,
            "issued_at": issued.isoformat() if issued else None}


def _side_identity(card):
    bet = card.get("betting") if isinstance(card.get("betting"), dict) else {}
    a = card.get("player1") if isinstance(card.get("player1"), dict) else {}
    b = card.get("player2") if isinstance(card.get("player2"), dict) else {}
    p1, p2 = str(a.get("id") or ""), str(b.get("id") or "")
    picked = str(bet.get("selection_id") or "")
    return (bool(str(card.get("event_id") or "").strip()) and bool(p1 and p2)
            and p1 != p2 and picked in (p1, p2)
            and picked == str(card.get("winner_id") or "")
            and bet.get("market") == "match_winner")


def _singles_approved(card):
    if str(card.get("prediction_family") or "").lower() == "doubles":
        return False
    context = " ".join(str(card.get(k) or "") for k in
                       ("competition", "tournament_level", "tournament")).lower()
    return not any(t in context for t in
                   ("doubles", "junior", "wheelchair", "exhibition"))


def shadow_card(card: dict, params: dict) -> dict:
    """Pure A1/A2/A3 and combined counterfactual. Never changes a public field."""
    if not isinstance(card, dict):
        raise TypeError("Expected native card dict")
    if not _side_identity(card) or not _singles_approved(card):
        raise ValueError("Invalid singles Match Winner identity")
    p = _prob(card.get("probability"))
    if p is None or p < .5:
        raise ValueError("Native selected winner must be model favorite")
    fair = _prob(card["betting"].get("fair_implied_probability"))
    timing = time_evidence(card)
    usable = bool(timing["valid"] and fair is not None)
    q = calibrate_market_only(fair, params) if usable else _clip(p)
    gap = abs(p-fair) if usable else None
    a1 = bool(usable and fair >= .5)
    a2 = bool(usable and fair >= .75)
    a3 = bool(usable and gap <= params["selector_experiments"]["gap_absolute_max"] + 1e-12)
    reason = ("ELIGIBLE" if a1 and a2 and a3 else
              "MISSING_OR_INVALID_PRESTART_FAIR" if not usable else
              "MODEL_MARKET_FAVORITE_DISAGREEMENT" if not a1 else
              "FAIR_BELOW_0_75" if not a2 else "GAP_ABOVE_0_10")
    out = deepcopy(card)
    out["shadow_research"] = {
        "shadow_probability": q,
        "shadow_probability_source": ("historical_atp_market_only_unverified"
                                      if usable else "original_model_fallback"),
        "shadow_fair_missing_or_invalid": not usable,
        "shadow_time_evidence": timing,
        "shadow_fair": fair if usable else None,
        "shadow_model_probability": p,
        "shadow_model_fair_absolute_gap": gap,
        "shadow_decisions": {
            "A1_market_rank_veto": a1,
            "A2_market_min_0_75": a2,
            "A3_gap_0_10": a3,
            "A1_A2_A3_combined": a1 and a2 and a3,
        },
        "shadow_exclusion_reason": reason,
        "shadow_eligible_for_actual_publication": False,
        "shadow_market_historical_fit_verified": False,
        "shadow_wta_slope_verified": False,
    }
    return out


def rank_shadow_candidates(cards: Iterable[dict], params: dict, *, variant: str) -> list[dict]:
    if variant not in set(params["selector_experiments"]["experiment_variants"]):
        raise ValueError("Unknown or unauthorized research variant")
    seen, accepted = set(), []
    for card in cards:
        row = shadow_card(card, params)
        key = str(row["event_id"]), str(row["betting"]["selection_id"])
        if key in seen:
            raise ValueError("Duplicate native event/selection")
        seen.add(key)
        if row["shadow_research"]["shadow_decisions"][variant]:
            accepted.append(row)
    return sorted(accepted, key=lambda row: (
        -row["shadow_research"]["shadow_probability"],
        str(row["event_id"]), str(row["betting"]["selection_id"])))


def append_only_shadow_rows(existing: Iterable[dict], candidate: Iterable[dict]) -> list[dict]:
    """Pure first-capture merge. An actual writer needs its native CAS/global lock."""
    out = [deepcopy(row) for row in existing]
    by_key = {}
    for row in out:
        key = str(row.get("event_id") or ""), str(row.get("model_version") or "")
        if not all(key) or key in by_key:
            raise ValueError("Ambiguous prior shadow record identity")
        by_key[key] = row
    for row in candidate:
        key = str(row.get("event_id") or ""), str(row.get("model_version") or "")
        if not all(key):
            raise ValueError("Missing canonical event/model identity")
        if key in by_key:
            prior = by_key[key]
            if any(prior.get(name) != row.get(name) for name in
                   ("player1_id", "player2_id", "scheduled_at", "tour")):
                raise ValueError("Conflicting event identity or schedule")
            continue
        new = deepcopy(row)
        if new.get("status") not in (None, "pending"):
            raise ValueError("Only pending first-captures may append")
        by_key[key] = new
        out.append(new)
    return out


def prepare_all_singles_shadow_rows(fixtures: Iterable[dict], params: dict) -> list[dict]:
    """Pure full-slate stage; not a provider caller, settlement engine or writer."""
    result, seen = [], set()
    for src in fixtures:
        if not isinstance(src, dict):
            raise ValueError("Invalid native fixture")
        event = str(src.get("event_id") or "").strip()
        version = str(src.get("model_version") or "").strip()
        a, b = str(src.get("player1_id") or ""), str(src.get("player2_id") or "")
        tour = str(src.get("tour") or "").upper().strip()
        if (not event or not version or not a or not b or a == b
                or tour not in ("ATP", "WTA") or src.get("prediction_family") != "singles"):
            raise ValueError("Requires unique canonical singles identity")
        key = event, version
        if key in seen:
            raise ValueError("Duplicate fixture/model identity")
        seen.add(key)
        start = _utc(src.get("scheduled_at"))
        captured = _utc(src.get("model_captured_at"))
        p = _prob(src.get("model_player1_probability"))
        if start is None or captured is None or captured >= start or p is None:
            raise ValueError("Model snapshot lacks immutable pre-start evidence")
        quote = _utc(src.get("market_captured_at"))
        issued = _utc(src.get("issued_at"))
        f1, f2 = _prob(src.get("fair_player1")), _prob(src.get("fair_player2"))
        valid = (f1 is not None and f2 is not None and
                 abs(f1 + f2 - 1) <= .0001 and
                 quote is not None and issued is not None and
                 quote <= issued < start and
                 bool(str(src.get("bookmaker") or "").strip()))
        result.append({
            "schema": 1, "status": "pending", "event_id": event,
            "model_version": version, "tour": tour,
            "competition": str(src.get("competition") or ""),
            "category_at_capture": str(src.get("category_at_capture") or ""),
            "surface": str(src.get("surface") or ""),
            "scheduled_at": start.isoformat(),
            "player1_id": a, "player2_id": b,
            "model_player1_probability": p,
            "model_captured_at": captured.isoformat(),
            "fair_player1": f1 if valid else None,
            "fair_player2": f2 if valid else None,
            "bookmaker": str(src.get("bookmaker") or "") if valid else None,
            "market_captured_at": quote.isoformat() if valid else None,
            "issued_at": issued.isoformat() if valid else None,
            "shadow_player1_probability": calibrate_market_only(f1, params) if valid else p,
            "shadow_source": "market_only_external_unverified" if valid else "model_fallback_no_valid_fair",
            "shadow_market_missing": not valid,
            "source_provenance": str(src.get("source_provenance") or ""),
            "result_winner_id": None, "shadow_read_only_no_publication": True,
        })
    return result


def select_daily_shadow_picks(cards: Iterable[dict], params: dict, *, n_min: int = 5) -> list[dict]:
    """A0: always return a ranked daily shadow shortlist, never publish it.

    N for each UTC match day is min(slate, max(n_min, number_of_T0)).
    Market conflict and missing quotes only lower rank; they do not remove
    otherwise valid single-match candidates. This is NOT an issuance/writer.
    """
    if type(n_min) is not int or n_min < 1:
        raise ValueError("n_min must be a positive integer")
    grouped: dict[str, list[dict]] = {}
    identities = set()
    for source in cards:
        candidate = shadow_card(source, params)
        day = _utc(candidate.get("scheduled_at"))
        if day is None:
            raise ValueError("Shadow day requires an unambiguous scheduled UTC time")
        date_utc = day.date().isoformat()
        betting = candidate["betting"]
        # One tip per canonical event across the entire captured slate;
        # opposite-side duplicates cannot inflate the A0 daily minimum.
        key = str(candidate["event_id"])
        if key in identities:
            raise ValueError("Duplicate canonical event in shadow slate")
        identities.add(key)
        research = candidate["shadow_research"]
        decisions = research["shadow_decisions"]
        if decisions["A1_A2_A3_combined"]:
            tier = "T0"
        elif research["shadow_fair_missing_or_invalid"]:
            tier = "T3"
        elif decisions["A1_market_rank_veto"]:
            tier = "T1"
        else:
            tier = "T2"
        basis = "fallback_model" if tier == "T3" else "rank_market"
        research["selection_tier"] = tier
        research["selection_basis"] = basis
        candidate["selection_tier"] = tier
        candidate["selection_basis"] = basis
        candidate["shadow_selection_day_utc"] = date_utc
        # Keep public fields/offer attributes untouched.
        grouped.setdefault(date_utc, []).append(candidate)
    selected = []
    for day in sorted(grouped):
        slate = sorted(grouped[day], key=lambda row: (
            row["selection_tier"],
            -row["shadow_research"]["shadow_probability"],
            str(row["event_id"]),
            str(row["betting"]["selection_id"]),
        ))
        t0 = sum(row["selection_tier"] == "T0" for row in slate)
        wanted = min(len(slate), max(n_min, t0))
        selected.extend(slate[:wanted])
    return selected
