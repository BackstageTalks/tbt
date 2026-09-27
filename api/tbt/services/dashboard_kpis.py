"""Admin-selected public dashboard scalars, without exposing private result windows.

These three global marketing cards are configured by an admin. Only the values
of the selected cards are sent to lower access tiers; raw historical windows,
result rows and alternative KPI values remain subject to existing entitlements.
The live current-day bet count and current accessible TOP odds stay per account
and are calculated from that user's authorized feed on the frontend.
"""
from __future__ import annotations

import math
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
    "avg_odds": {"today", *(str(day) for day in WINDOW_DAYS)},
    "roi": {str(day) for day in WINDOW_DAYS},
    "yield_units": {str(day) for day in WINDOW_DAYS},
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
        if metric not in ALLOWED_PERIODS or period not in ALLOWED_PERIODS[metric]:
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


def selected_dashboard_cards(feed: dict, ui_config: dict | None) -> list[dict]:
    """Expose only admin-selected scalars, not the full rolling performance.

    Results and betting metrics come from the immutable issued production feed.
    ROI and unit yield retain the existing Short Odds exclusion in _betting_metrics.
    """
    windows = feed.get("performance_windows") or {}
    if not isinstance(windows, dict):
        windows = {}
    best = feed.get("dashboard_model_success") or {}
    output = []
    for card in normalize_cards(ui_config):
        metric, period = card["metric"], card["period"]
        value = None
        if metric == "model_success" and period == "auto":
            value = _finite(best.get("accuracy") if isinstance(best, dict) else None)
        elif metric == "today_picks" or (metric == "avg_odds" and period == "today"):
            # Account-specific figures must be calculated from authorized rows.
            pass
        else:
            window = windows.get(period) or {}
            model = window.get("model") or {}
            betting = window.get("betting") or {}
            overall = betting.get("overall") or {}
            if metric == "model_success" and (model.get("n") or 0) > 0:
                value = _finite(model.get("accuracy"))
            elif metric == "avg_odds" and (overall.get("n") or 0) > 0:
                value = _finite(overall.get("avg_odds"))
            elif metric in ("roi", "yield_units") and (_finite(overall.get("staked_units")) or 0) > 0:
                value = _finite(overall.get("roi" if metric == "roi" else "profit_units"))
        output.append({**card, "value": value})
    return output
