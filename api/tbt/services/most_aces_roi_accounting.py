"""Strict read-only financial accounting for actual issued Most Aces Results.

Shared by private feed CLI and persisted Azure archive diagnostics. No writes,
provider calls, model inference or authentication changes occur here.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import math

from .dashboard_kpis import published_results_metrics
from .most_aces_pricing import PRICE_BASIS


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def audit(feed: dict) -> dict:
    counts, errors = Counter(), Counter()
    unique, accepted = {}, []
    profit = 0.0
    for row in feed.get("results") or []:
        for p in row.get("market_publications") or []:
            if p.get("market") != "most_aces":
                continue
            counts["observed_publications"] += 1
            if p.get("excluded_reason"):
                counts["excluded"] += 1
                continue
            if not p.get("issued_at"):
                counts["unissued"] += 1
                continue
            key = p.get("publication_key")
            if not key:
                errors["missing_publication_key"] += 1
                continue
            signature = json.dumps([row.get("event_id"), row.get("scheduled_at"), p], sort_keys=True)
            if key in unique:
                if unique[key] != signature:
                    errors["conflicting_duplicate"] += 1
                else:
                    counts["identical_duplicates"] += 1
                continue
            unique[key] = signature
            try:
                issued = datetime.fromisoformat(p["issued_at"].replace("Z", "+00:00"))
                start = datetime.fromisoformat(row["scheduled_at"].replace("Z", "+00:00"))
                valid_time = issued.utcoffset() is not None and start.utcoffset() is not None and issued < start
            except (KeyError, TypeError, ValueError):
                valid_time = False
            if not valid_time or p.get("price_contract") != "player_superiority" or p.get("section") != "ace_winner":
                errors["invalid_issued_contract"] += 1
                continue
            result = p.get("result") or {}
            if result.get("void") is True or result.get("status") in {"void", "push"}:
                counts["void"] += 1
                continue
            correct = result.get("correct")
            if type(correct) is not bool:
                counts["pending"] += 1
                continue
            odds = _number(p.get("odds"))
            if p.get("price_status") != "priced_projection" or odds is None or odds <= 1:
                counts["settled_unpriced"] += 1
                continue
            if p.get("price_basis") == PRICE_BASIS and not 1.50 <= odds <= 1.70:
                errors["local_quote_outside_band"] += 1
                continue
            expected = odds - 1 if correct else -1.0
            gain = _number(result.get("profit_units"))
            stake = _number(result.get("staked_units"))
            if stake != 1 or gain is None or not math.isclose(gain, expected, abs_tol=1e-9):
                errors["frozen_quote_accounting_mismatch"] += 1
                continue
            counts["wins" if correct else "losses"] += 1
            counts["local_priced" if p.get("price_basis") == PRICE_BASIS else "other_priced"] += 1
            profit += expected
            accepted.append({**row, "market_publications": [p]})
    n = counts["wins"] + counts["losses"]
    metrics = published_results_metrics({"results": accepted}, "all")
    if metrics["stake_count"] != n or not math.isclose(metrics["profit_units"], profit, abs_tol=1e-9):
        errors["dashboard_accounting_mismatch"] += 1
    return {
        "schema": 1,
        "status": "FAIL" if errors else "VERIFIED_ACCOUNTING" if n else "INSUFFICIENT_SETTLED_EVIDENCE",
        "counts": dict(counts), "errors": dict(errors), "settled_priced": n,
        "profit_units": profit, "roi": profit / n if n else None,
        "scope": "supplied_results_snapshot_accounting_only",
        "profitability_established": False, "member_render_verified": False,
        "provider_requests": 0, "production_writes": 0,
    }
