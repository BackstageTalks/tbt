from __future__ import annotations

from typing import Any


def public_prediction(row: dict[str, Any]) -> dict[str, Any]:
    p1 = float(row.get("player1_probability") or 0.5)
    p2 = float(row.get("player2_probability") or (1.0 - p1))
    return {
        "id": row.get("match_id"),
        "match_id": row.get("match_id"),
        "scheduled_at": row.get("scheduled_at"),
        "tour": str(row.get("tour") or "").upper(),
        "tournament": row.get("tournament") or "",
        "surface": row.get("surface") or "unknown",
        "round": row.get("round_name") or "",
        "player1": {
            "id": row.get("player1_id"),
            "name": row.get("player1_name"),
            "rank": row.get("player1_rank"),
            "win_probability": round(p1, 5),
            "win_probability_pct": round(p1 * 100.0, 2),
        },
        "player2": {
            "id": row.get("player2_id"),
            "name": row.get("player2_name"),
            "rank": row.get("player2_rank"),
            "win_probability": round(p2, 5),
            "win_probability_pct": round(p2 * 100.0, 2),
        },
        "prediction": {
            "winner_id": row.get("predicted_winner_id"),
            "winner_name": row.get("predicted_winner_name"),
            "probability_pct": round(float(row.get("confidence_pct") or max(p1, p2) * 100), 2),
            "confidence_band": row.get("confidence_band") or "low",
            "signals": row.get("signals") or [],
        },
        "model_version": row.get("model_version"),
        "generated_at": row.get("generated_at"),
        "settled": row.get("is_correct") is not None,
        "is_correct": row.get("is_correct"),
    }


def blinq_flat_prediction(row: dict[str, Any]) -> dict[str, Any]:
    rich = public_prediction(row)
    return {
        "id": rich["match_id"],
        "date": rich["scheduled_at"],
        "tour": rich["tour"],
        "tournament": rich["tournament"],
        "surface": rich["surface"],
        "p1": rich["player1"]["name"],
        "p2": rich["player2"]["name"],
        "p1_id": rich["player1"]["id"],
        "p2_id": rich["player2"]["id"],
        "p1_prob": rich["player1"]["win_probability_pct"],
        "p2_prob": rich["player2"]["win_probability_pct"],
        "pick": rich["prediction"]["winner_name"],
        "pick_id": rich["prediction"]["winner_id"],
        "probability": rich["prediction"]["probability_pct"],
        "confidence": rich["prediction"]["confidence_band"],
        "model": rich["model_version"],
        "signals": rich["prediction"]["signals"],
    }
