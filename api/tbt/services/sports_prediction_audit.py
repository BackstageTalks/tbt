"""Price-independent, pre-match audit. Never relabel model scores as validated trust."""
from copy import deepcopy
from datetime import datetime
from math import isfinite


def sports_prediction_audit(rows, generated_at):
    output = []
    for row in rows:
        if not isinstance(row, dict) or row.get("prediction_family") == "doubles":
            continue
        players = [row.get(side) if isinstance(row.get(side), dict) else {} for side in ("player1", "player2")]
        ids = [str(p.get("id") or "") for p in players]
        winner = str(row.get("winner_id") or "")
        reasons = []
        if not row.get("event_id") or not all(ids) or ids[0] == ids[1] or winner not in ids:
            reasons.append("invalid_identity")
        probability = None
        try:
            ps = [float(p["probability"]) for p in players]
            if not all(isfinite(p) and 0 < p < 1 for p in ps) or abs(sum(ps) - 1) > .005:
                raise ValueError()
            probability = ps[ids.index(winner)]
            if probability < .5:
                raise ValueError()
        except (KeyError, IndexError, ValueError, TypeError):
            reasons.append("invalid_probability")
        try:
            start = datetime.fromisoformat(row["scheduled_at"].replace("Z", "+00:00"))
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            if not (created <= generated_at < start) or not row.get("model_version"):
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            reasons.append("missing_prematch_model_evidence")
        quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
        output.append({
            "event_id": row.get("event_id"), "winner_id": winner,
            "model_version": row.get("model_version"),
            "model_probability_before_depth_adjustment": probability,
            "status": "predicted" if not reasons else "unavailable",
            "reasons": reasons, "reliability_status": "cohort_validation_required",
            "statistics_evidence": {
                side: deepcopy((quality.get(side) or {}).get("statistics_evidence")) if isinstance(quality.get(side), dict) else None
                for side in ("player1", "player2")},
        })
    valid = sorted((r for r in output if not r["reasons"]),
                   key=lambda r: (-r["model_probability_before_depth_adjustment"], str(r["event_id"])))
    seen = set()
    position = 0
    for row in valid:
        if row["event_id"] in seen:
            row["reasons"].append("duplicate_event")
            row["status"] = "unavailable"
            continue
        seen.add(row["event_id"])
        position += 1
        row["sports_rank"] = position
    return output
