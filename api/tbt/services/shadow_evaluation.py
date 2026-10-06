"""Private challenger-vs-production shadow evaluation.

The shadow ledger is never part of the public prediction feed.  It records the
first pre-match probability from the current production model and candidate
model on the same fixture, then settles those immutable snapshots from canonical
completed history.  A new candidate version automatically starts a new cohort.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ..models.metrics import evaluate_probabilities
from ..schemas import MatchRecord
from .engine import _match_void_reason


MIN_SHADOW_MATCHES = 200
MIN_SHADOW_DAYS = 3


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Shadow timestamps must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("match_id") or ""),
        str(row.get("production_model_version") or ""),
        str(row.get("challenger_model_version") or ""),
    )


def _prediction_index(rows: Iterable[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        match_id = str(row.get("id") or row.get("match_id") or "").strip()
        if match_id:
            result[match_id] = row
    return result


def _p1_probability(row: dict) -> float:
    player1 = row.get("player1")
    if not isinstance(player1, dict):
        raise ValueError("Shadow prediction is missing player1")
    value = float(player1.get("probability"))
    if not 0.0 < value < 1.0:
        raise ValueError("Shadow probability must be strictly between 0 and 1")
    return value


def _prediction_players(row: dict) -> tuple[str, str]:
    player1 = row.get("player1")
    player2 = row.get("player2")
    if not isinstance(player1, dict) or not isinstance(player2, dict):
        raise ValueError("Shadow prediction is missing players")
    return str(player1.get("id") or ""), str(player2.get("id") or "")


def update_shadow_ledger(
    ledger: Iterable[dict],
    *,
    production_predictions: Iterable[dict] = (),
    challenger_predictions: Iterable[dict] = (),
    completed_matches: Iterable[MatchRecord] = (),
    production_model_version: str = "",
    challenger_model_version: str = "",
    now: datetime | None = None,
) -> list[dict]:
    """Settle prior rows and append first immutable same-fixture snapshots."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = [dict(row) for row in ledger if isinstance(row, dict)]

    completed_by_id = {
        str(match.match_id): match
        for match in completed_matches
        if match.is_completed
    }

    # Settlement never requires the current challenger artifact.  This means a
    # previously captured cohort can finish even if a later retrain replaces it.
    for row in rows:
        if row.get("status") not in (None, "", "pending"):
            continue
        match = completed_by_id.get(str(row.get("match_id") or ""))
        if match is None:
            continue
        void_reason = _match_void_reason(match)
        if void_reason:
            row.update({
                "status": "void",
                "excluded_reason": void_reason,
                "result_winner_id": match.winner_id,
                "settled_at": now.isoformat(),
            })
            continue
        player1_id = str(row.get("player1_id") or "")
        player2_id = str(row.get("player2_id") or "")
        if match.winner_id not in {player1_id, player2_id}:
            row.update({
                "status": "excluded",
                "excluded_reason": "winner_identity_mismatch",
                "result_winner_id": match.winner_id,
                "settled_at": now.isoformat(),
            })
            continue
        target = 1 if match.winner_id == player1_id else 0
        production_p = float(row["production_player1_probability"])
        challenger_p = float(row["challenger_player1_probability"])
        row.update({
            "status": "settled",
            "target_player1_win": target,
            "result_winner_id": match.winner_id,
            "production_correct": bool((production_p >= 0.5) == bool(target)),
            "challenger_correct": bool((challenger_p >= 0.5) == bool(target)),
            "settled_at": now.isoformat(),
        })

    production = _prediction_index(production_predictions)
    challenger = _prediction_index(challenger_predictions)
    if not production_model_version or not challenger_model_version:
        return sorted(rows, key=lambda row: (
            str(row.get("scheduled_at") or ""),
            str(row.get("match_id") or ""),
            str(row.get("challenger_model_version") or ""),
        ))

    existing = {_row_key(row) for row in rows}
    for match_id in sorted(set(production) & set(challenger)):
        prod = production[match_id]
        chal = challenger[match_id]
        key = (match_id, str(production_model_version), str(challenger_model_version))
        if key in existing:
            continue

        prod_players = _prediction_players(prod)
        chal_players = _prediction_players(chal)
        if prod_players != chal_players or not all(prod_players):
            continue

        prod_scheduled = _utc(str(prod.get("scheduled_at") or ""))
        chal_scheduled = _utc(str(chal.get("scheduled_at") or ""))
        if prod_scheduled != chal_scheduled or now >= prod_scheduled:
            continue

        p_prod = _p1_probability(prod)
        p_chal = _p1_probability(chal)
        rows.append({
            "schema": 1,
            "match_id": match_id,
            "event_id": str(prod.get("event_id") or ""),
            "tour": str(prod.get("tour") or ""),
            "surface": str(prod.get("surface") or ""),
            "tournament": str(prod.get("tournament") or ""),
            "scheduled_at": prod_scheduled.isoformat(),
            "player1_id": prod_players[0],
            "player2_id": prod_players[1],
            "production_model_version": str(production_model_version),
            "challenger_model_version": str(challenger_model_version),
            "production_player1_probability": p_prod,
            "challenger_player1_probability": p_chal,
            "production_predicted_winner_id": (
                prod_players[0] if p_prod >= 0.5 else prod_players[1]
            ),
            "challenger_predicted_winner_id": (
                chal_players[0] if p_chal >= 0.5 else chal_players[1]
            ),
            "captured_at": now.isoformat(),
            "status": "pending",
            "result_winner_id": None,
        })
        existing.add(key)

    return sorted(rows, key=lambda row: (
        str(row.get("scheduled_at") or ""),
        str(row.get("match_id") or ""),
        str(row.get("challenger_model_version") or ""),
    ))


def _delta(challenger: dict, production: dict, key: str) -> float | None:
    left = challenger.get(key)
    right = production.get(key)
    if left is None or right is None:
        return None
    return float(left) - float(right)


def build_shadow_report(
    ledger: Iterable[dict],
    *,
    production_model_version: str,
    challenger_model_version: str,
    min_matches: int = MIN_SHADOW_MATCHES,
    min_days: int = MIN_SHADOW_DAYS,
) -> dict:
    """Evaluate only the active exact model-pair cohort."""
    cohort = [
        row for row in ledger
        if isinstance(row, dict)
        and str(row.get("production_model_version") or "") == str(production_model_version)
        and str(row.get("challenger_model_version") or "") == str(challenger_model_version)
    ]
    settled = [row for row in cohort if row.get("status") == "settled"]
    y = [int(row["target_player1_win"]) for row in settled]
    prod_p = [float(row["production_player1_probability"]) for row in settled]
    chal_p = [float(row["challenger_player1_probability"]) for row in settled]

    production = evaluate_probabilities(y, prod_p)
    challenger = evaluate_probabilities(y, chal_p)
    challenger_only = sum(
        bool(row.get("challenger_correct")) and not bool(row.get("production_correct"))
        for row in settled
    )
    production_only = sum(
        bool(row.get("production_correct")) and not bool(row.get("challenger_correct"))
        for row in settled
    )

    n = len(settled)
    settled_days = sorted({
        _utc(str(row.get("scheduled_at"))).date().isoformat()
        for row in settled
        if row.get("scheduled_at")
    })
    min_matches_met = n >= int(min_matches)
    min_days_met = len(settled_days) >= int(min_days)
    accuracy_not_worse = (
        n > 0 and challenger.get("accuracy", 0.0) >= production.get("accuracy", 0.0)
    )
    log_loss_better = (
        n > 0 and challenger.get("log_loss", float("inf")) < production.get("log_loss", float("inf"))
    )
    brier_better = (
        n > 0 and challenger.get("brier_score", float("inf")) < production.get("brier_score", float("inf"))
    )
    ece_not_worse = (
        n > 0 and challenger.get("ece_10", float("inf")) <= production.get("ece_10", float("inf"))
    )
    ready = bool(
        min_matches_met
        and min_days_met
        and accuracy_not_worse
        and log_loss_better
        and brier_better
        and ece_not_worse
    )

    return {
        "schema": 1,
        "production_model_version": str(production_model_version),
        "challenger_model_version": str(challenger_model_version),
        "cohort": {
            "captured": len(cohort),
            "settled": n,
            "pending": sum(row.get("status") == "pending" for row in cohort),
            "void": sum(row.get("status") == "void" for row in cohort),
            "excluded": sum(row.get("status") == "excluded" for row in cohort),
            "minimum_for_review": int(min_matches),
            "minimum_days_for_review": int(min_days),
            "settled_utc_days": len(settled_days),
        },
        "production": production,
        "challenger": challenger,
        "delta_challenger_minus_production": {
            key: _delta(challenger, production, key)
            for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
        },
        "paired": {
            "challenger_only_correct": challenger_only,
            "production_only_correct": production_only,
            "discordant": challenger_only + production_only,
        },
        "gate": {
            "minimum_matches_met": min_matches_met,
            "minimum_days_met": min_days_met,
            "accuracy_not_worse": accuracy_not_worse,
            "log_loss_better": log_loss_better,
            "brier_better": brier_better,
            "ece_not_worse": ece_not_worse,
            "ready_for_promotion_review": ready,
            "automatic_promotion": False,
        },
    }
