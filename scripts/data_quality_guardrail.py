from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from _bootstrap import ROOT
from tbt.data.history_source import default_history_dir, load_training_history

VALID_TOURS = {"atp", "wta"}
VALID_SURFACES = {"hard", "clay", "grass", "indoor_hard", "carpet", "unknown"}
MAX_MISSING_PLAYER_RATIO = 0.001
MAX_INVALID_WINNER_RATIO = 0.001
MAX_FUTURE_COMPLETED_DAYS = 2


def ratio(n: int, d: int) -> float:
    return n / d if d else 0.0


def main() -> None:
    matches = load_training_history(default_history_dir(ROOT), root=ROOT)
    now = datetime.now(timezone.utc)

    match_ids = [str(m.match_id) for m in matches]
    duplicates = len(match_ids) - len(set(match_ids))
    missing_players = sum(not m.player1_id or not m.player2_id for m in matches)
    invalid_winner = sum(
        bool(m.winner_id) and str(m.winner_id) not in {str(m.player1_id), str(m.player2_id)}
        for m in matches
    )
    invalid_tour = sum(str(m.tour).lower() not in VALID_TOURS for m in matches)
    invalid_surface = sum(str(m.surface or "unknown").lower() not in VALID_SURFACES for m in matches)
    future_completed = sum(m.scheduled_at > now + timedelta(days=MAX_FUTURE_COMPLETED_DAYS) for m in matches)

    by_year = Counter(m.scheduled_at.astimezone(timezone.utc).year for m in matches)
    failures: list[str] = []
    warnings: list[str] = []

    if duplicates:
        failures.append(f"duplicate match_id rows: {duplicates}")
    if ratio(missing_players, len(matches)) > MAX_MISSING_PLAYER_RATIO:
        failures.append(f"missing player ratio too high: {ratio(missing_players, len(matches)):.4%}")
    if ratio(invalid_winner, len(matches)) > MAX_INVALID_WINNER_RATIO:
        failures.append(f"invalid winner ratio too high: {ratio(invalid_winner, len(matches)):.4%}")
    if invalid_tour:
        failures.append(f"invalid tour rows: {invalid_tour}")
    if invalid_surface:
        warnings.append(f"invalid/unknown surface-domain rows: {invalid_surface}")
    if future_completed:
        failures.append(f"completed matches too far in future: {future_completed}")

    # Never infer completeness from count alone. Pre-2025 is explicitly allowed to be
    # partial until direct provider backfill finishes.
    for year, count in sorted(by_year.items()):
        if year < 2025 and count < 1000:
            warnings.append(f"{year}: only {count} rows; cold history remains partial/unverified")

    report = {
        "ok": not failures,
        "source": "private GitHub Release yearly Parquet partitions",
        "supabase_history_read": False,
        "canonical_completed_matches": len(matches),
        "years": dict(sorted(by_year.items())),
        "duplicate_match_ids": duplicates,
        "missing_players": missing_players,
        "invalid_winners": invalid_winner,
        "invalid_tours": invalid_tour,
        "invalid_surfaces": invalid_surface,
        "future_completed": future_completed,
        "warnings": warnings,
        "failures": failures,
    }

    path = ROOT / "reports" / "data_quality_guardrail.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
