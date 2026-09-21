"""Plan a hard Tennis RapidAPI cap for player-card presentation enrichment.

The enrichment script always attempts two ranking snapshot calls (ATP/WTA) before
its optional per-player phases. This planner reserves those calls and scales the
requested phase caps so the whole run, not each phase independently, stays under
one operator-visible ceiling. A refresh report can be supplied so presentation
enrichment consumes only requests left after the prediction refresh.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OVERHEAD_REQUESTS = 2
PHASES = (
    ("photo", "BLINQ_ENRICH_PHOTO_CAP"),
    ("player_detail", "BLINQ_ENRICH_DETAIL_CAP"),
    ("fallback_ranking", "BLINQ_ENRICH_FALLBACK_RANK_CAP"),
    ("tournament_logo", "BLINQ_ENRICH_LOGO_CAP"),
)


def _nonnegative(value: int, name: str) -> int:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return int(value)


def _refresh_requests(path: str | None) -> int:
    if not path:
        return 0
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Refresh report not found: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    value = int(payload.get("requests") or 0)
    return max(0, value)


def plan(total_cap: int, requested: dict[str, int], *, already_used: int = 0) -> dict:
    total_cap = _nonnegative(total_cap, "total_cap")
    already_used = _nonnegative(already_used, "already_used")
    requested = {name: _nonnegative(int(requested.get(name, 0)), name) for name, _ in PHASES}
    remaining = max(0, total_cap - already_used)
    if remaining < OVERHEAD_REQUESTS:
        phase_caps = {name: 0 for name, _ in PHASES}
        overhead = 0
    else:
        overhead = OVERHEAD_REQUESTS
        phase_budget = remaining - overhead
        requested_total = sum(requested.values())
        if requested_total <= phase_budget:
            phase_caps = dict(requested)
        elif requested_total == 0 or phase_budget <= 0:
            phase_caps = {name: 0 for name, _ in PHASES}
        else:
            # Proportional scaling preserves the operator's relative phase intent.
            exact = {name: requested[name] * phase_budget / requested_total for name, _ in PHASES}
            phase_caps = {name: min(requested[name], int(exact[name])) for name, _ in PHASES}
            left = phase_budget - sum(phase_caps.values())
            # Deterministic largest-remainder allocation; never exceed requested cap.
            order = sorted(
                (name for name, _ in PHASES),
                key=lambda name: (exact[name] - int(exact[name]), requested[name], name),
                reverse=True,
            )
            while left > 0:
                progressed = False
                for name in order:
                    if phase_caps[name] < requested[name]:
                        phase_caps[name] += 1
                        left -= 1
                        progressed = True
                        if left == 0:
                            break
                if not progressed:
                    break
    planned = overhead + sum(phase_caps.values())
    return {
        "total_cap": total_cap,
        "already_used": already_used,
        "remaining_before_enrichment": remaining,
        "ranking_snapshot_overhead": overhead,
        "phase_caps": phase_caps,
        "planned_enrichment_max": planned,
        "planned_total_max": already_used + planned,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--total-cap", type=int, required=True)
    ap.add_argument("--refresh-report")
    ap.add_argument("--photo", type=int, default=250)
    ap.add_argument("--fallback-ranking", type=int, default=100)
    ap.add_argument("--player-detail", type=int, default=250)
    ap.add_argument("--tournament-logo", type=int, default=120)
    ap.add_argument("--github-env")
    args = ap.parse_args(argv)
    result = plan(
        args.total_cap,
        {
            "photo": args.photo,
            "fallback_ranking": args.fallback_ranking,
            "player_detail": args.player_detail,
            "tournament_logo": args.tournament_logo,
        },
        already_used=_refresh_requests(args.refresh_report),
    )
    env_values = {
        "BLINQ_ENRICH_PHOTO_CAP": result["phase_caps"]["photo"],
        "BLINQ_ENRICH_FALLBACK_RANK_CAP": result["phase_caps"]["fallback_ranking"],
        "BLINQ_ENRICH_DETAIL_CAP": result["phase_caps"]["player_detail"],
        "BLINQ_ENRICH_LOGO_CAP": result["phase_caps"]["tournament_logo"],
        "BLINQ_ENRICH_PLANNED_MAX": result["planned_enrichment_max"],
    }
    if args.github_env:
        with Path(args.github_env).open("a", encoding="utf-8") as handle:
            for key, value in env_values.items():
                handle.write(f"{key}={value}\n")
    print(json.dumps({**result, "env": env_values}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
