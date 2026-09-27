"""Admin-selected public dashboard scalars, without exposing private result windows.

These three global marketing cards are configured by an admin. Only the values
of the selected cards are sent to lower access tiers; raw historical windows,
result rows and alternative KPI values remain subject to existing entitlements.
The live current-day bet count and current accessible TOP odds stay per account
and are calculated from that user's authorized feed on the frontend.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

WINDOW_DAYS = (3, 7, 14, 30, 180, 365)
DEFAULT_CARDS = (
    {"metric": "today_picks", "period": "today"},
    {"metric": "model_success", "period": "auto"},
    {"metric": "avg_odds", "period": "today"},
)
PERIODS = {str(day) for day in WINDOW_DAYS}
RESULT_PERIODS = {"auto", "all", *PERIODS}
ALLOWED_PERIODS = {
    "today_picks": {"today"},
    "model_success": {"auto", *PERIODS},  # legacy auto policy stays unchanged
    "avg_odds": {"today", "auto", *PERIODS},
    "roi": RESULT_PERIODS,  # existing published Results financial source
    "yield_units": RESULT_PERIODS,
    "winner_roi": RESULT_PERIODS,
    "winner_yield_units": RESULT_PERIODS,
    "results_success": RESULT_PERIODS,
    "results_top_success": RESULT_PERIODS,
    "results_avg_odds": RESULT_PERIODS,
    "auto_success": {"auto"},
    "auto_odds": {"auto"},
    "auto_roi": {"auto"},
    "auto_yield": {"auto"},
}

# "Automatic" family choices compare values ONLY within the same unit:
# rates against rates, bookmaker odds against odds, net % against net %, and
# units against units. Never compare a percentage against units or an odd.
AUTO_FAMILIES = {
    "auto_success": ("model_success", "results_success", "results_top_success"),
    "auto_odds": ("avg_odds", "results_avg_odds"),
    "auto_roi": ("winner_roi", "roi"),
    "auto_yield": ("winner_yield_units", "yield_units"),
}
RESULT_METRICS = {"results_success", "results_top_success", "results_avg_odds",
                  "roi", "yield_units", "winner_roi", "winner_yield_units"}
AUTO_PERIODS = tuple(str(day) for day in WINDOW_DAYS)



def normalize_cards(ui_config: dict | None) -> list[dict[str, str]]:
    """Tolerate absent legacy runtime config; never trust unrecognized metrics."""
    dashboard = ui_config.get("dashboard") if isinstance(ui_config, dict) else None
    supplied = dashboard.get("kpi_cards") if isinstance(dashboard, dict) else None
    if not isinstance(supplied, list) or len(supplied) != 3:
        return [dict(card) for card in DEFAULT_CARDS]
    result = []
    for slot, raw in enumerate(supplied):
        metric = raw.get("metric") if isinstance(raw, dict) else None
        period = str(raw.get("period") or "") if isinstance(raw, dict) else ""
        if not isinstance(metric, str) or metric not in ALLOWED_PERIODS or period not in ALLOWED_PERIODS[metric]:
            result.append(dict(DEFAULT_CARDS[slot]))
        else:
            result.append({"metric": metric, "period": period})
    return result


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None



# Mirror the public Results table rather than the winner-model ledger or the
# financial-only betting window. Results counts graded projection-only Aces,
# DF, Sets and Games in its W/L record even when they have no genuine odds.
_RESULTS_SECTIONS = {"top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}
_PROJECTION_MARKETS = {"aces", "double_faults", "sets", "games"}
_VOID_STATUSES = {
    "void", "push", "cancelled", "canceled", "postponed", "walkover",
    "walk over", "w/o", "retired", "ret", "abandoned", "interrupted",
    "suspended", "no_action",
}


def _result_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _result_identity(row: dict, publication: dict, index: int) -> str:
    """Match canonicalResultPublicationKey in the public Results browser."""
    event = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
    market = str(publication.get("market") or "match_winner").strip().lower()
    scope = str(publication.get("projection_scope") or "").strip().lower()
    metric = str(publication.get("projection_metric") or "").strip().lower()
    selection = str(publication.get("selection_id") or publication.get("selection") or "").strip().lower()
    if event and selection:
        return f"{event}::{market}::{scope}::{metric}::{selection}"
    def normalize_name(value: Any) -> str:
        folded = unicodedata.normalize("NFKD", str(value or ""))
        return re.sub(r"[^a-zA-Z0-9]+", " ", "".join(ch for ch in folded if not unicodedata.combining(ch))).strip().lower()
    p1, p2 = row.get("player1") or {}, row.get("player2") or {}
    players = "::".join(sorted(filter(None, (
        normalize_name(p1.get("id") or p1.get("name")),
        normalize_name(p2.get("id") or p2.get("name")),
    ))))
    scheduled = str(row.get("scheduled_at") or "").strip()
    if (scheduled or players) and selection:
        return f"{scheduled}::{players}::{market}::{scope}::{metric}::{selection}"
    return str(publication.get("selection_key") or publication.get("publication_key") or f"{scheduled}::{players}::{publication.get('section') or ''}::{selection or index}")


def _result_outcome(publication: dict) -> str:
    result = publication.get("result") or {}
    raw = str(
        result.get("status") or result.get("outcome") or result.get("settlement")
        or result.get("result") or ""
    ).strip().lower()
    if result.get("void") is True or result.get("is_void") is True or raw in _VOID_STATUSES:
        return "void"
    if result.get("correct") is True:
        return "win"
    if result.get("correct") is False:
        return "loss"
    return "pending"


def published_results_metrics(feed: dict, period: str, category: str = "all",
                              *, now: datetime | None = None) -> dict:
    """Use exactly the available public Results rows, including the 1000-row cap.

    Category=all covers all eight actual published product sections and
    statistical projections; TOP selects only top_daily before deduplication.
    Returned hit rate and average quote mirror localResultMetrics in the UI.
    """
    if period != "all" and period not in {str(day) for day in WINDOW_DAYS}:
        raise ValueError("Unsupported Results dashboard period")
    if category not in {"all", "top_daily", "winner_singles"}:
        raise ValueError("Unsupported Results dashboard category")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Results dashboard clock must have a timezone")
    cutoff = None if period == "all" else now.astimezone(timezone.utc) - timedelta(days=int(period))
    unique: dict[str, dict] = {}
    for row in feed.get("results") or []:
        if not isinstance(row, dict):
            continue
        scheduled = _result_datetime(row.get("scheduled_at"))
        if cutoff is not None and (scheduled is None or scheduled < cutoff):
            continue
        for index, p in enumerate(row.get("market_publications") or []):
            if not isinstance(p, dict) or not p.get("issued_at") or not isinstance(p.get("result"), dict) or p.get("excluded_reason"):
                continue
            section = str(p.get("section") or "").strip().lower()
            market = str(p.get("market") or "").strip().lower()
            if section not in _RESULTS_SECTIONS and market not in {"aces", "double_faults"}:
                continue
            if category == "top_daily" and section != "top_daily":
                continue
            if category == "winner_singles" and (
                market != "match_winner" or section == "doubles"
                or str(row.get("prediction_family") or "").lower() == "doubles"
            ):
                continue
            if _result_outcome(p) == "pending":
                continue
            key = _result_identity(row, p, index)
            prior = unique.get(key)
            issued = _result_datetime(p.get("issued_at"))
            if prior is None or (
                issued is not None and
                (prior["_issued"] is None or issued < prior["_issued"])
            ):
                unique[key] = {"publication": p, "_issued": issued}
    wins = losses = odds_count = unit_sample = 0
    odds_sum = staked_units = profit_units = 0.0
    for entry in unique.values():
        p = entry["publication"]
        outcome = _result_outcome(p)
        if outcome == "void":
            continue
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            continue
        status = str(p.get("price_status") or "").strip().lower()
        market = str(p.get("market") or "").strip().lower()
        priced = status == "priced_projection" if market in _PROJECTION_MARKETS else status in {"", "priced", "priced_projection"}
        quote = _finite(p.get("odds"))
        if priced and quote is not None and quote > 1:
            odds_sum += quote
            odds_count += 1
            # Exactly the public Results ROI denominator: paid/settled genuine
            # quotes only. Short Odds contributes W/L, but not stake or profit.
            if str(p.get("section") or "").strip().lower() != "prime":
                result = p.get("result") or {}
                stake = _finite(result.get("staked_units"))
                profit = _finite(result.get("profit_units"))
                if stake is not None and stake > 0 and profit is not None:
                    staked_units += stake
                    profit_units += profit
                    unit_sample += 1
    total = wins + losses
    return {
        "wins": wins, "losses": losses, "sample": total,
        "hit_rate": wins / total if total else None,
        "avg_odds": odds_sum / odds_count if odds_count else None,
        "odds_sample": odds_count,
        "staked_units": staked_units, "profit_units": profit_units,
        "unit_sample": unit_sample,
        "roi": profit_units / staked_units if staked_units > 0 else None,
    }


def _metric_value(feed: dict, metric: str, period: str,
                  results_cache: dict[tuple[str, str], dict],
                  windows: dict, best: dict, *, now: datetime | None) -> tuple[float | None, int]:
    """(Value, valid sample). A financial sample is actual, settled stakes."""
    if metric in RESULT_METRICS and isinstance(feed.get("results"), list):
        category = ("top_daily" if metric == "results_top_success" else
                    "winner_singles" if metric in {"winner_roi", "winner_yield_units"} else "all")
        key = (period, category)
        if key not in results_cache:
            results_cache[key] = published_results_metrics(feed, period, category, now=now)
        summary = results_cache[key]
        field = {
            "results_success": "hit_rate", "results_top_success": "hit_rate",
            "results_avg_odds": "avg_odds", "roi": "roi", "yield_units": "profit_units",
            "winner_roi": "roi", "winner_yield_units": "profit_units",
        }[metric]
        sample_key = ("odds_sample" if metric == "results_avg_odds" else
                      "unit_sample" if metric in {"roi", "yield_units", "winner_roi", "winner_yield_units"}
                      else "sample")
        n = int(summary[sample_key])
        # 0u without a single financial stake is *not* a valid maximum.
        return (_finite(summary[field]) if n > 0 else None), n

    if metric in {"winner_roi", "winner_yield_units"}:
        # The old feed does not contain a separate singles-only financial
        # summary. Never pretend the mixed Results ROI is winners-only.
        return None, 0
    if metric == "model_success" and period == "auto":
        return _finite(best.get("accuracy")), int(best.get("n") or 0)
    if metric == "today_picks" or (metric == "avg_odds" and period == "today"):
        return None, 0  # calculated per account from today's authorized picks
    window = windows.get(period) or {}
    model = window.get("model") or {}
    betting = window.get("betting") or {}
    overall = betting.get("overall") or {}
    if metric == "model_success":
        n = int(model.get("n") or 0)
        return (_finite(model.get("accuracy")) if n > 0 else None), n
    if metric == "avg_odds":
        top = (betting.get("sections") or {}).get("top_daily") or {}
        n = int(top.get("n") or 0)
        return (_finite(top.get("avg_odds")) if n > 0 else None), n
    # Older feeds without a results array retain the original financial KPI
    # windows; new feeds use the exact capped public Results sample above.
    if metric in {"roi", "yield_units"}:
        stake = _finite(overall.get("staked_units")) or 0
        return (_finite(overall.get("roi" if metric == "roi" else "profit_units"))
                if stake > 0 else None), int(overall.get("n") or 0)
    return None, 0


def _best_metric(feed: dict, metrics: tuple[str, ...], results_cache: dict,
                 windows: dict, best: dict, *, now: datetime | None) -> dict | None:
    """Highest finite value among all eligible windows and data sources.

    Tie breaks prefer the larger measured sample; then shorter horizon. Auto
    never invents a price/stake for projection-only or void publications.
    """
    chosen = None
    for metric in metrics:
        periods = (*AUTO_PERIODS, "all") if metric in RESULT_METRICS else AUTO_PERIODS
        for period in periods:
            value, sample = _metric_value(feed, metric, period, results_cache, windows, best, now=now)
            if value is None or sample <= 0:
                continue
            candidate = {
                "value": value, "sample": sample,
                "selected_metric": metric, "selected_period": period,
            }
            score = (value, sample, -(366 if period == "all" else int(period)))
            if chosen is None or score > chosen[0]:
                chosen = (score, candidate)
    return chosen[1] if chosen else None


def selected_dashboard_cards(feed: dict, ui_config: dict | None, *, now: datetime | None = None) -> list[dict]:
    """Only the three selected KPI scalars reach restricted user tiers.

    Automatic mode compares all available 3/7/14/30/180/365-day candidates
    and (for Results) the entire available public Results sample. Selected
    source, period and sample accompany auto scalars for admin-only preview;
    no extra cards or explanations are added to the public dashboard.
    """
    windows = feed.get("performance_windows") or {}
    if not isinstance(windows, dict):
        windows = {}
    best = feed.get("dashboard_model_success") or {}
    results_cache: dict[tuple[str, str], dict] = {}
    output = []
    for card in normalize_cards(ui_config):
        metric, period = card["metric"], card["period"]
        if metric in AUTO_FAMILIES:
            resolved = _best_metric(feed, AUTO_FAMILIES[metric], results_cache, windows, best, now=now)
        elif period == "auto" and metric != "model_success":
            resolved = _best_metric(feed, (metric,), results_cache, windows, best, now=now)
        else:
            value, sample = _metric_value(feed, metric, period, results_cache, windows, best, now=now)
            resolved = {"value": value, "sample": sample} if value is not None else None
        if resolved is None:
            output.append({**card, "value": None})
        elif metric in AUTO_FAMILIES or (period == "auto" and metric != "model_success"):
            output.append({**card, **resolved})
        else:
            output.append({**card, "value": resolved["value"]})
    return output
