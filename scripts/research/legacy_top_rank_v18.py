"""Frozen v18 research baseline; never use for new production selections."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from tbt.services.market_selection import _top_quality_rank, _selection_identity
TOP_MIN_COUNT=3
TOP_TARGET_COUNT=3
TOP_MIN_PROBABILITY=.60
TOP_MIN_ODDS=1.50
TOP_FALLBACK_MIN_ODDS=1.50
TOP_BACKUP_MIN_DATA_DEPTH=.75
TOP_BACKUP_MIN_SURFACE_MATCHES=3
TOP_MIN_DATA_DEPTH=.80
TOP_MIN_SURFACE_MATCHES=5

def _rank_full_slate_top(core: list[dict[str, Any]], backup: list[dict[str, Any]],
                         *, target: int = TOP_TARGET_COUNT,
                         minimum: int = TOP_MIN_COUNT) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """One TOP offer: three highest-ranked real priced, evidence-qualified picks.

    Backup uses a controlled 0.75 depth / 3 surface matches floor if the
    standard 0.80 / 5 pool cannot supply three. Never creates a quote.
    """
    selected = sorted(core, key=_top_quality_rank, reverse=True)[:target]
    appended = 0
    seen = {_selection_identity(item) for item in selected}
    if len(selected) < minimum:
        for item in sorted(backup, key=_top_quality_rank, reverse=True):
            if len(selected) >= minimum or len(selected) >= target:
                break
            key = _selection_identity(item)
            if not key or key in seen:
                continue
            selected.append(deepcopy(item))
            seen.add(key)
            appended += 1
        selected.sort(key=_top_quality_rank, reverse=True)
    return selected, appended, {
        "step": 1 if appended else 0,
        "min_probability": TOP_MIN_PROBABILITY,
        "min_odds": TOP_FALLBACK_MIN_ODDS,
        "target": target, "minimum": minimum,
        "core_pool": len(core), "backup_pool": len(backup),
        "backup_selected": appended, "shortfall": max(0, minimum-len(selected)),
        "rank": "harmonic_model_market_consensus_evidence",
    }
