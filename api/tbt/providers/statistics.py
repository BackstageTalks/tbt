"""Conservative normalisation of whole-match TennisApi statistics.

Only an unambiguous ``ALL`` period is accepted. Rate fields and raw count fields
are kept separate so an integer such as ``8`` aces can never be mistaken for an
800% rate. Unknown shapes still fail closed.
"""
from __future__ import annotations

import math
import re

from ..errors import ProviderError


class NoSupportedStatisticsError(ProviderError):
    """Valid statistics payload that contains none of the fields we consume."""

from ..utils import normalize_rate


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def _fraction(item, side):
    """Prefer counts, then explicit fractions/percentages; never guess count units."""
    won, total = _number(item.get(side + "Value")), _number(item.get(side + "Total"))
    if won is not None and total is not None and total > 0 and won <= total:
        return won / total, won, total
    text = str(item.get(side, "")).strip()
    ratio = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if ratio:
        won, total = map(float, ratio.groups())
        if total > 0 and won <= total:
            return won / total, won, total
    percent = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent:
        value = normalize_rate(percent.group(0))
        if value is not None:
            return value, None, None
    return None, None, None


def _count(item, side):
    """Extract a raw non-negative whole-match count without inventing units."""
    # SofaScore-like payloads commonly expose the raw number either directly in
    # ``home``/``away`` or in ``homeValue``/``awayValue``. Do not use *Total
    # fields here: for serve ratios those are denominators, not event counts.
    for key in (side + "Value", side):
        raw = item.get(key)
        if isinstance(raw, str):
            text = raw.strip()
            # Reject ratios/percentages for a count statistic.
            if not text or "/" in text or "%" in text:
                continue
        value = _number(raw)
        if value is not None:
            return value
    return None


def _whole_point_count(item, side):
    """Accept only consistent explicit non-negative integer point-count fields.

    When both raw and display fields are present, they must agree exactly.
    A malformed explicit field is not permission to fall back to another.
    """
    observed = []
    for field in (side + "Value", side):
        if field not in item or item[field] is None:
            continue
        raw = item[field]
        if type(raw) is int:
            value = raw
        elif type(raw) is float and math.isfinite(raw) and raw.is_integer():
            value = int(raw)
        elif isinstance(raw, str) and re.fullmatch(r"[0-9]{1,7}", raw.strip()):
            value = int(raw.strip())
        else:
            return None
        if not 0 <= value <= 1_000_000:
            return None
        observed.append(value)
    return observed[0] if observed and len(set(observed)) == 1 else None


def _set_bp_counts_exceed_all(periods, *, home_is_player1, saved, scored):
    """Veto *newly derived* BP rates if observed set counts exceed ALL.

    Set tapes can be incomplete, so a lower sum is not a contradiction.
    Unparseable or missing set counts cannot establish a match-level rate.
    """
    totals = {side: {"saved": 0, "faced": 0, "scored": 0}
              for side in ("p1", "p2")}
    for period in periods:
        if not isinstance(period, dict):
            continue
        label = str(period.get("period") or "").strip().upper()
        if not re.fullmatch(r"(?:[1-5](?:ST|ND|RD|TH)?|S[1-5]|SET\s*[1-5])", label):
            continue
        groups = period.get("groups")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            items = group.get("statisticsItems")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = re.sub(r"[^a-z0-9]", "",
                             str(item.get("key") or item.get("name") or "").lower())
                if key not in {"breakpointssaved", "breakpointsscored"}:
                    continue
                for side in ("home", "away"):
                    player = "p1" if (side == "home") == home_is_player1 else "p2"
                    if key == "breakpointssaved":
                        _, won, faced = _fraction(item, side)
                        if (won is not None and faced is not None
                                and won.is_integer() and faced.is_integer()):
                            totals[player]["saved"] += int(won)
                            totals[player]["faced"] += int(faced)
                    else:
                        won = _count(item, side)
                        if won is not None and won.is_integer():
                            totals[player]["scored"] += int(won)
    for player in ("p1", "p2"):
        if player in saved:
            won, faced = saved[player]
            if (totals[player]["saved"] > won or
                    totals[player]["faced"] > faced):
                return True
        if player in scored and totals[player]["scored"] > scored[player]:
            return True
    return False

RATE_ALIASES = {
    "firstservepoints": "first_serve_win", "firstservepointswon": "first_serve_win",
    "1stservepointswon": "first_serve_win", "1stservepoints": "first_serve_win",
    "secondservepoints": "second_serve_win", "secondservepointswon": "second_serve_win",
    "2ndservepointswon": "second_serve_win", "2ndservepoints": "second_serve_win",
    "servicepointswon": "service_points_won", "servicepoints": "service_points_won",
    "returnpointswon": "return_points_won", "returnpoints": "return_points_won",
    "breakpointsconverted": "break_points_won",
    # Native 2026 ALL-period key observed in 200 paid provider responses.
    # Only count-backed (won/total) or explicit percent shapes are accepted by
    # _fraction; an unqualified "scored" count must NEVER become a rate.
    # Preserve the same return-side field/identity conflict checks as
    # breakPointsConverted. Provider groups label this a return statistic.
    "breakpointsscored": "break_points_won",
    # Direct saved/faced ratio; not inferred from generic service points.
    "breakpointssaved": "break_point_serve_win",
    # TennisApi names verified in provider-probe 2026-09-23. Serve placement
    # (firstServeAccuracy) is NOT the same as points won on first serve.
    "firstserveaccuracy": "first_serve_in",
    "firstservepointsaccuracy": "first_serve_win",
    "secondservepointsaccuracy": "second_serve_win",
    "firstreturnpoints": "first_return_win",
    "secondreturnpoints": "second_return_win",
}

# Direct observed point COUNTS, not point-win percentages or totals.
_WHOLE_POINT_COUNT_ALIASES = {
    "servicepointsscored": "service",
    "receiverpointsscored": "receiver",
    "pointstotal": "won_total",
}

COUNT_ALIASES = {
    "ace": "aces",
    "aces": "aces",
    "doublefault": "double_faults",
    "doublefaults": "double_faults",
    "doublefaulterrors": "double_faults",
}

def inventory_statistics_keys(payload: dict) -> dict[str, object]:
    """Inventory every ALL-period key, including partly successful responses.

    Read-only diagnostics: no raw values, credentials or player identities enter
    the report. Non-ALL set keys are kept separately so they cannot be mistaken
    for whole-match features. Unknown envelopes do not become trusted inputs.
    """
    periods = payload.get("statistics") if isinstance(payload, dict) else None
    if not isinstance(periods, list):
        return {"supported": [], "unsupported": [], "set_only": [], "invalid_envelope": True}
    supported, unsupported, set_only = set(), set(), set()
    for period in periods:
        if not isinstance(period, dict):
            continue
        period_name = str(period.get("period", "")).upper()
        groups = period.get("groups")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("statisticsItems"), list):
                continue
            for item in group["statisticsItems"]:
                if not isinstance(item, dict):
                    continue
                key = re.sub(r"[^a-z0-9]", "", str(item.get("key") or item.get("name") or "").lower())
                if not key:
                    continue
                if period_name != "ALL":
                    set_only.add(key)
                elif key in RATE_ALIASES or key in COUNT_ALIASES or key in _WHOLE_POINT_COUNT_ALIASES:
                    supported.add(key)
                else:
                    unsupported.add(key)
    return {"supported": sorted(supported), "unsupported": sorted(unsupported),
            "set_only": sorted(set_only), "invalid_envelope": False}


def complete_opponent_service_rates(values: dict[str, float]) -> bool:
    """Recover missing complementary whole-match service and return rates.

    These are complementary outcomes on the *same* service points. Do not use
    first-serve placement percentages or unweighted first/second percentages.
    Existing explicit statistics always take precedence. A player's whole-match
    service win rate equally determines their opponent's return win rate.
    """
    changed = False
    for prefix, opponent in (("p1", "p2"), ("p2", "p1")):
        service_field = f"{prefix}_service_points_won"
        return_field = f"{opponent}_return_points_won"
        for target, source in ((service_field,return_field),(return_field,service_field)):
            rate = values.get(source)
            if values.get(target) is not None or rate is None:
                continue
            if isinstance(rate,bool) or not isinstance(rate,(int,float)) or not math.isfinite(rate):
                continue
            if not 0 <= rate <= 1:
                continue
            values[target] = 1.0 - rate
            changed = True
    return changed


def parse_statistics(payload: dict, *, home_is_player1: bool) -> dict[str, float]:
    if payload == {} or payload.get("statistics") == []:
        return {}
    periods = payload.get("statistics")
    if not isinstance(periods, list):
        raise ProviderError("Unsupported statistics envelope; preserve sample and update adapter")
    whole = [p for p in periods if isinstance(p, dict) and str(p.get("period", "")).upper() == "ALL"]
    if len(whole) != 1 or not isinstance(whole[0].get("groups"), list):
        raise ProviderError("Missing unambiguous ALL period in statistics")

    values: dict[str, float] = {}
    rate_counts = {}
    # Bare converted-BP counts require an independently observed denominator.
    bp_saved_counts = {}
    bp_scored_counts = {}
    point_counts = {}
    point_counts_unreliable = False
    for group in whole[0]["groups"]:
        if not isinstance(group, dict):
            continue
        for item in group.get("statisticsItems", []):
            if not isinstance(item, dict):
                continue
            key = re.sub(r"[^a-z0-9]", "", str(item.get("key") or item.get("name") or "").lower())
            rate_name = RATE_ALIASES.get(key)
            count_name = COUNT_ALIASES.get(key)
            count_kind = _WHOLE_POINT_COUNT_ALIASES.get(key)
            if count_kind:
                for side in ("home", "away"):
                    count = _whole_point_count(item, side)
                    if count is None:
                        if side + "Value" in item or side in item:
                            point_counts_unreliable = True
                        continue
                    identity = (side, count_kind)
                    if identity in point_counts and point_counts[identity] != count:
                        point_counts_unreliable = True
                    point_counts[identity] = count
                continue
            if not rate_name and not count_name:
                continue

            for side in ("home", "away"):
                prefix = "p1" if (side == "home") == home_is_player1 else "p2"
                if count_name:
                    count = _count(item, side)
                    if count is None:
                        continue
                    field = f"{prefix}_{count_name}"
                    if field in values and abs(values[field] - count) > 1e-6:
                        raise ProviderError(f"Conflicting whole-match statistic: {field}")
                    values[field] = count
                    continue

                value, won, total = _fraction(item, side)
                if (key == "breakpointsscored"
                        and item.get(side + "Total") is None):
                    observed = _count(item, side)
                    if observed is not None and observed.is_integer():
                        bp_scored_counts[prefix] = int(observed)
                if value is None:
                    continue
                field = f"{prefix}_{rate_name}"
                if field in values and abs(values[field] - value) > 1e-6:
                    raise ProviderError(f"Conflicting whole-match statistic: {field}")
                values[field] = value
                if rate_name == "break_points_won":
                    # A converted break point is an observed return-side point.
                    # Retain the existing break_points_won model alias too.
                    bp_field = f"{prefix}_break_point_return_win"
                    if bp_field in values and abs(values[bp_field] - value) > 1e-6:
                        raise ProviderError(f"Conflicting whole-match statistic: {bp_field}")
                    values[bp_field] = value
                if total is not None:
                    rate_counts[field] = (won, total)
                    if (rate_name == "break_point_serve_win"
                            and won is not None and won.is_integer()
                            and total.is_integer()):
                        bp_saved_counts[prefix] = (int(won), int(total))

    # Independent set totals can disprove even internally consistent ALL BP.
    # Fail closed on new conversion-rate derivation; retain direct evidence.
    set_bp_contradiction = _set_bp_counts_exceed_all(
        periods, home_is_player1=home_is_player1,
        saved=bp_saved_counts, scored=bp_scored_counts,
    )
    # Opponent saved/faced BPs imply conversion chances for this player.
    # Only accept the rate if the independent converted count also agrees.
    # Missing counts, 0/0 and disagreements must never become a BP rate.
    for player, opponent in (("p1", "p2"), ("p2", "p1")):
        if set_bp_contradiction:
            continue
        saved = bp_saved_counts.get(opponent)
        converted = bp_scored_counts.get(player)
        if saved is None or converted is None:
            continue
        saved_count, faced = saved
        if faced <= 0 or converted != faced - saved_count:
            continue
        rate = converted / faced
        targets = (f"{player}_break_points_won",
                   f"{player}_break_point_return_win")
        if any(field in values and abs(values[field] - rate) > 1e-6
               for field in targets):
            continue
        for field in targets:
            values.setdefault(field, rate)

    # Weighted return quality is computed from *return-point* wins and chances;
    # do not average percentages or mistake a first-serve-in rate for quality.
    for prefix in ("p1", "p2"):
        first, second = (rate_counts.get(f"{prefix}_{kind}_return_win") for kind in ("first", "second"))
        if first is not None and second is not None and first[1] + second[1] > 0:
            field = f"{prefix}_return_points_won"
            derived = (first[0] + second[0]) / (first[1] + second[1])
            if field in values and abs(values[field] - derived) > 1e-6:
                raise ProviderError(f"Conflicting whole-match statistic: {field}")
            values.setdefault(field, derived)

    for prefix, opponent in (("p1", "p2"), ("p2", "p1")):
        first, second = (rate_counts.get(f"{prefix}_{kind}_serve_win") for kind in ("first", "second"))
        if first is not None and second is not None and first[1] + second[1] > 0:
            service = (first[0] + second[0]) / (first[1] + second[1])
            service_field = f"{prefix}_service_points_won"
            if service_field in values and abs(values[service_field] - service) > 1e-6:
                raise ProviderError(f"Conflicting whole-match statistic: {service_field}")
            values.setdefault(service_field, service)
            values.setdefault(f"{opponent}_return_points_won", 1 - service)

    # A verified opponent's whole-match return rate also tells us the fraction
    # of own service points won, even when serve-specific fields are absent.
    complete_opponent_service_rates(values)
    
    # Preserve verified point denominators; percentage-only inputs stay count-less.
    for prefix in ("p1", "p2"):
        for rate, parts in (
            ("service_points_won", ("first_serve_win", "second_serve_win")),
            ("return_points_won", ("first_return_win", "second_return_win")),
        ):
            field = f"{prefix}_{rate}"
            observed = rate_counts.get(field)
            if observed is None:
                first = rate_counts.get(f"{prefix}_{parts[0]}")
                second = rate_counts.get(f"{prefix}_{parts[1]}")
                if first is not None and second is not None:
                    observed = (first[0] + second[0], first[1] + second[1])
            if observed is None or values.get(field) is None:
                continue
            won, total = observed
            if total > 0 and won <= total and abs(won / total - values[field]) < 1e-8:
                name = "service_points_total" if rate == "service_points_won" else "return_points_total"
                values[f"{prefix}_{name}"] = float(total)

    # Complementary service/return denominators describe the same points.
    for prefix, opponent in (("p1", "p2"), ("p2", "p1")):
        for own_rate, own_total, other_rate, other_total in (
            ("service_points_won", "service_points_total",
             "return_points_won", "return_points_total"),
            ("return_points_won", "return_points_total",
             "service_points_won", "service_points_total"),
        ):
            rate = values.get(f"{prefix}_{own_rate}")
            complementary = values.get(f"{opponent}_{other_rate}")
            points = values.get(f"{prefix}_{own_total}")
            if (rate is not None and complementary is not None and points is not None
                    and abs(rate + complementary - 1.) < 1e-8):
                values.setdefault(f"{opponent}_{other_total}", points)


    # Reuse ALL-period counts from this same response. Opponent's receiver
    # points WON close the exact denominator of each player's service points.
    # Optional pointsTotal is WON by that player, not points served.
    # Missing or internally contradictory count evidence creates no rates.
    mandatory = ((side, kind) for side in ("home", "away")
                 for kind in ("service", "receiver"))
    if not point_counts_unreliable and all(key in point_counts for key in mandatory):
        hs, away_service = point_counts["home", "service"], point_counts["away", "service"]
        hr, away_receive = point_counts["home", "receiver"], point_counts["away", "receiver"]
        home_serves, away_serves = hs + away_receive, away_service + hr
        agrees = (
            home_serves > 0 and away_serves > 0
            and point_counts.get(("home", "won_total"), hs + hr) == hs + hr
            and point_counts.get(("away", "won_total"), away_service + away_receive)
                == away_service + away_receive
        )
        if agrees:
            home = "p1" if home_is_player1 else "p2"
            away = "p2" if home_is_player1 else "p1"
            derived = {
                f"{home}_service_points_won": hs / home_serves,
                f"{away}_return_points_won": away_receive / home_serves,
                f"{away}_service_points_won": away_service / away_serves,
                f"{home}_return_points_won": hr / away_serves,
                f"{home}_service_points_total": float(home_serves),
                f"{away}_return_points_total": float(home_serves),
                f"{away}_service_points_total": float(away_serves),
                f"{home}_return_points_total": float(away_serves),
            }
            for field, value in derived.items():
                current = values.get(field)
                tol = 0.0 if field.endswith("_total") else 1e-6
                if current is not None and abs(current - value) > tol:
                    raise ProviderError(f"Conflicting whole-match statistic: {field}")
                values.setdefault(field, value)

    if not values:
        raise NoSupportedStatisticsError("Statistics contain no supported rate/count fields; no imputation performed")
    return values
