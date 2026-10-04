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
ALLOWED_PERIODS = {
    "today_picks": {"today"},
    "model_success": {"auto", *(str(day) for day in WINDOW_DAYS)},
    "avg_odds": {"today", "auto", *(str(day) for day in WINDOW_DAYS)},
    "winner_avg_odds": {"auto", *(str(day) for day in WINDOW_DAYS)},
    "auto_success": {"auto"},
    "auto_avg_odds": {"auto"},
    "auto_roi": {"auto"},
    "auto_yield_units": {"auto"},
    "roi": {"auto", *(str(day) for day in WINDOW_DAYS)},
    "yield_units": {"auto", *(str(day) for day in WINDOW_DAYS)},
    "winner_roi": {"auto", *(str(day) for day in WINDOW_DAYS)},
    "winner_yield_units": {"auto", *(str(day) for day in WINDOW_DAYS)},
    "results_roi": {"auto", "all", *(str(day) for day in WINDOW_DAYS)},
    "results_yield_units": {"auto", "all", *(str(day) for day in WINDOW_DAYS)},
    "results_success": {"auto", "all", *(str(day) for day in WINDOW_DAYS)},
    "results_top_success": {"auto", "all", *(str(day) for day in WINDOW_DAYS)},
    "results_avg_odds": {"auto", "all", *(str(day) for day in WINDOW_DAYS)},
}


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
_RESULTS_SECTIONS = { "top_daily", "prime", "value", "doubles", "ace", "double_faults", "sets", "games"}
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
    if category not in {"all", "top_daily", "winners"}:
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
            if not isinstance(p, dict) or not isinstance(p.get("result"), dict) or p.get("excluded_reason"):
                continue
            if not p.get("issued_at") and p["result"].get("runtime_source") != "match_status_snapshot":
                continue
            section = str(p.get("section") or "").strip().lower()
            market = str(p.get("market") or "").strip().lower()
            if section not in _RESULTS_SECTIONS and market not in {"aces", "double_faults"}:
                continue
            if category == "top_daily" and section != "top_daily":
                continue
            if category == "winners" and (market != "match_winner" or section == "doubles"
                                            or str(row.get("prediction_family") or "").lower() == "doubles"):
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
    wins = losses = odds_count = 0
    odds_sum = 0.0
    staked = profit = 0.0
    stake_count = 0
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
            if str(p.get("section") or "").strip().lower() == "prime":
                continue
            result = p.get("result") or {}
            stake, gain = _finite(result.get("staked_units")), _finite(result.get("profit_units"))
            if stake is not None and stake > 0 and gain is not None:
                staked += stake
                profit += gain
                stake_count += 1
    total = wins + losses
    return {
        "wins": wins, "losses": losses, "sample": total,
        "hit_rate": wins / total if total else None,
        "avg_odds": odds_sum / odds_count if odds_count else None,
        "odds_sample": odds_count,
        "staked_units": staked, "profit_units": profit,
        "roi": profit / staked if staked > 0 else None,
        "stake_count": stake_count,
    }


# Keep the original financial categories for backward-compatible saved admin
# configs. The new Results finance metrics use precisely the same capped,
# deduplicated ledger rows as the public Results table.
RESULTS_METRICS = {
    "results_success": ("all", "hit_rate"),
    "results_top_success": ("top_daily", "hit_rate"),
    "results_avg_odds": ("all", "avg_odds"),
    "winner_avg_odds": ("winners", "avg_odds"),
    "results_roi": ("all", "roi"),
    "results_yield_units": ("all", "profit_units"),
    "winner_roi": ("winners", "roi"),
    "winner_yield_units": ("winners", "profit_units"),
}
# Auto compares both independent source calculations (and all their periods).
AUTO_COMPARISONS = {
    "auto_success": ("model_success", "results_success"),
    "auto_avg_odds": ("winner_avg_odds", "results_avg_odds"),
    "auto_roi": ("winner_roi", "results_roi"),
    "auto_yield_units": ("winner_yield_units", "results_yield_units"),
}
AUTO_DAYS = WINDOW_DAYS


def _metric_window_value(feed: dict, metric: str, period: str,
                         cache: dict, *, now: datetime | None = None) -> tuple[float | None, int]:
    if metric in RESULTS_METRICS:
        category, field = RESULTS_METRICS[metric]
        key = (period, category)
        if key not in cache:
            cache[key] = published_results_metrics(feed, period, category, now=now)
        stats = cache[key]
        # A zero-profit portfolio is valid if it contains settled real stakes.
        size = stats["stake_count"] if field in {"roi", "profit_units"} else (
            stats["odds_sample"] if field == "avg_odds" else stats["sample"]
        )
        return (_finite(stats[field]) if size > 0 else None), size
    window = (feed.get("performance_windows") or {}).get(period) or {}
    model = window.get("model") or {}
    betting = window.get("betting") or {}
    if metric == "model_success":
        n = int(model.get("n") or 0)
        return (_finite(model.get("accuracy")) if n > 0 else None), n
    if metric == "avg_odds":
        top = (betting.get("sections") or {}).get("top_daily") or {}
        n = int(top.get("n") or 0)
        return (_finite(top.get("avg_odds")) if n > 0 else None), n
    if metric in {"roi", "yield_units"}:
        overall = betting.get("overall") or {}
        stake = _finite(overall.get("staked_units")) or 0.0
        field = "roi" if metric == "roi" else "profit_units"
        return (_finite(overall.get(field)) if stake > 0 else None), int(overall.get("n") or 0)
    return None, 0


def _auto_best(feed: dict, metric: str, cache: dict,
               *, now: datetime | None = None) -> tuple[float | None, str | None, int]:
    periods = [str(d) for d in AUTO_DAYS]
    if metric in RESULTS_METRICS:
        periods.append("all")
    eligible = []
    for period in periods:
        value, sample = _metric_window_value(feed, metric, period, cache, now=now)
        if value is not None and sample > 0:
            eligible.append((value, sample, period))
    if eligible:
        # Maximize the actual KPI, not the category; deterministic ties prefer
        # more observations, then longer periods, then ALL. Do not promote empty
        # or fabricated 0%/0u samples to a winning candidate.
        value, n, period = max(eligible, key=lambda row: (row[0], row[1],
            9999 if row[2] == "all" else int(row[2])))
        return value, period, n
    return None, None, 0


def _auto_across_sources(feed: dict, metric: str, cache: dict,
                         *, now: datetime | None = None) -> tuple[float | None, str | None, str | None, int]:
    """Choose maximum KPI value across the winner and Results sources and horizons."""
    if metric not in AUTO_COMPARISONS:
        return None, None, None, 0
    candidates = []
    for source in AUTO_COMPARISONS[metric]:
        periods = [str(day) for day in AUTO_DAYS]
        if source in RESULTS_METRICS and RESULTS_METRICS[source][0] == "all":
            periods.append("all")
        for period in periods:
            value, sample = _metric_window_value(feed, source, period, cache, now=now)
            if value is not None and sample > 0:
                duration = 9999 if period == "all" else int(period)
                candidates.append((value, sample, duration, source, period))
    if not candidates:
        return None, None, None, 0
    value, sample, _, source, period = max(candidates)
    return value, source, period, sample


def selected_dashboard_cards(feed: dict, ui_config: dict | None, *, now: datetime | None = None) -> list[dict]:
    """Return only three configured scalar values; auto selects each metric's
    highest valid time-window value without mixing winner and Results samples."""
    output = []
    cache: dict[tuple[str, str], dict] = {}
    best = feed.get("dashboard_model_success") or {}
    for card in normalize_cards(ui_config):
        metric, period = card["metric"], card["period"]
        value = None
        selected_period = None
        sample = 0
        selected_source = None
        if metric == "today_picks" or metric == "avg_odds" and period == "today":
            # Always calculated from the authorized current offer on the client.
            pass
        elif metric in AUTO_COMPARISONS:
            value, selected_source, selected_period, sample = _auto_across_sources(
                feed, metric, cache, now=now
            )
        elif period == "auto":
            value, selected_period, sample = _auto_best(feed, metric, cache, now=now)
            # Compatibility with old feeds where the aggregate auto sample is
            # available but individual windows have not yet been rebuilt.
            if metric == "model_success" and value is None:
                value = _finite(best.get("accuracy") if isinstance(best, dict) else None)
        else:
            value, sample = _metric_window_value(feed, metric, period, cache, now=now)
        output.append({**card, "value": value, **({"selected_period": selected_period,
            "sample": sample, **({"selected_source": selected_source} if selected_source else {})}
            if period == "auto" else {})})
    return output
