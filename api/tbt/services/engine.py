"""Offline prediction publication with immutable pre-match records."""
from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pandas as pd

from ..models.feature_builder import FeatureBuilder, FEATURE_NAMES
from ..models.metrics import evaluate_probabilities
from .prediction_quality import coverage, subgroup_report


def event_id(match):
    raw = match.provider_payload or {}
    return str(next((raw.get(k) for k in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id") if raw.get(k)), match.match_id))


def predict(model, history, upcoming, now=None):
    now = now or datetime.now(timezone.utc)
    # Match completion timestamps are unavailable. Use previous UTC days only,
    # matching the conservative whole-day training protocol.
    builder = FeatureBuilder()
    builder.replay(history, before=now.replace(hour=0, minute=0, second=0, microsecond=0))
    future = sorted((m for m in upcoming if not m.is_completed and m.scheduled_at > now
                     and m.status in {"upcoming", "notstarted", "scheduled"}), key=lambda m: (m.scheduled_at, m.match_id))
    if not future:
        return []
    features = [builder.snapshot(m) for m in future]
    probabilities = model.predict_proba(pd.DataFrame(features, columns=FEATURE_NAMES))
    rows = []
    for match, f, probability in zip(future, features, probabilities):
        p = float(probability)
        if not np.isfinite(p) or not 0 < p < 1:
            raise ValueError("Invalid model probability")
        winner = match.player1_id if p >= .5 else match.player2_id
        factors = [("Sila na povrchu", f["surface_elo_diff"], .12),
                   ("Celková výkonnosť", f["elo_diff"], .12),
                   ("Aktuálna forma", f["recent_form_diff"], .08),
                   ("Servis", f["serve_quality_diff"], .04)]
        signals = [{"label": name, "player_id": match.player1_id if value >= 0 else match.player2_id}
                   for name, value, scale in sorted(factors, key=lambda x: abs(x[1] / x[2]), reverse=True)
                   if abs(value) >= scale][:3]
        rows.append({"id": match.match_id, "event_id": event_id(match), "tour": match.tour.upper(),
            "scheduled_at": match.scheduled_at.isoformat(), "tournament": match.tournament,
            "surface": match.surface, "round": match.round_name,
            "competition": match.tournament_level or "unknown", "quality": coverage(builder, match),
            "player1": {"id": match.player1_id, "name": match.player1_name, "probability": p},
            "player2": {"id": match.player2_id, "name": match.player2_name, "probability": 1 - p},
            "winner_id": winner, "confidence": max(p, 1 - p), "data_depth": f["data_depth"],
            "stats_available": bool(f["stats_known_both"]), "signals": signals,
            "model_version": model.version, "created_at": now.isoformat(),
            "issued_at": None, "publication_status": "pending", "result": None})
    return rows


def reconcile_ledger(ledger, predictions, history, now=None):
    now = now or datetime.now(timezone.utc)
    stored = {row["event_id"]: dict(row) for row in ledger}
    for row in predictions:
        # Freeze the first prediction. Never rewrite history after learning result.
        if datetime.fromisoformat(row["scheduled_at"]) <= now:
            continue
        if row["event_id"] not in stored:
            stored[row["event_id"]] = {
                **row,
                "issued_at": None,
                "publication_status": "pending",
            }
        existing = stored[row["event_id"]]
        if {existing["player1"]["id"], existing["player2"]["id"]} != {row["player1"]["id"], row["player2"]["id"]}:
            raise ValueError("Prediction identity mismatch")
        if existing.get("result") is None:
            existing.setdefault("original_scheduled_at", existing["scheduled_at"])
            existing["scheduled_at"] = row["scheduled_at"]
    completed = {event_id(m): m for m in history if m.is_completed}
    for key, row in stored.items():
        match = completed.get(key)
        if match is None or row.get("result") is not None:
            continue
        if {row["player1"]["id"], row["player2"]["id"]} != {match.player1_id, match.player2_id}:
            raise ValueError("Settlement identity mismatch")
        issued_at = row.get("issued_at")
        if not issued_at:
            # Pending predictions are never scored until a successful public
            # deployment confirms that they were actually available pre-match.
            continue
        # If the provider moves a start earlier than issuance, exclude that record
        # from live performance rather than claiming a pre-match prediction.
        if datetime.fromisoformat(issued_at) >= match.scheduled_at:
            row["excluded_reason"] = "issued_after_actual_start"
            continue
        row["result"] = {"winner_id": match.winner_id, "correct": row["winner_id"] == match.winner_id,
                         "settled_at": now.isoformat()}
    return sorted(stored.values(), key=lambda r: r["scheduled_at"])



def confirm_publication(ledger, published_event_ids, now=None):
    """Confirm first public availability after a successful deployment.

    Only event IDs present in the deployed feed are eligible for confirmation.
    Confirmation is conservative: if the match has already started, the record
    is excluded rather than backdated. Existing issued_at values are immutable.
    """
    now = now or datetime.now(timezone.utc)
    published = {str(value) for value in published_event_ids}
    confirmed = []
    for source in ledger:
        row = dict(source)
        if row.get("issued_at") or row.get("event_id") not in published:
            confirmed.append(row)
            continue
        scheduled_at = datetime.fromisoformat(row["scheduled_at"])
        if scheduled_at <= now:
            row["publication_status"] = "expired_unpublished"
            row["excluded_reason"] = "not_confirmed_before_start"
        else:
            row["issued_at"] = now.isoformat()
            row["publication_status"] = "published"
        confirmed.append(row)
    return sorted(confirmed, key=lambda r: r["scheduled_at"])

def serving_feed(ledger, model, history, report, upcoming, now=None):
    now = now or datetime.now(timezone.utc)
    future = {event_id(m) for m in upcoming if m.scheduled_at > now
              and not m.is_completed and m.status in {"upcoming", "notstarted", "scheduled"}}
    results = [row for row in ledger if row.get("result") is not None and not row.get("excluded_reason")]
    metrics = evaluate_probabilities(
        [int(r["result"]["winner_id"] == r["player1"]["id"]) for r in results],
        [r["player1"]["probability"] for r in results]) if results else {}
    quality_frame = pd.DataFrame([{'target': int(r['result']['winner_id'] == r['player1']['id']),
        'tour': r['tour'], 'surface': r['surface'], 'competition': r.get('competition', 'unknown'),
        'tournament': r.get('tournament', 'unknown'),
        'history_band': r.get('quality', {}).get('history_band', 'unknown'),
        'surface_history_band': r.get('quality', {}).get('surface_history_band', 'unknown')} for r in results])
    quality_report = subgroup_report(quality_frame, [r['player1']['probability'] for r in results]) if results else {}
    return {"schema": 1, "ready": True, "generated_at": now.isoformat(),
            "model": {"version": model.version, "report": report, "objective": "accuracy"},
            "upcoming": [r for r in ledger if r["event_id"] in future and r.get("result") is None
                         and datetime.fromisoformat(r["scheduled_at"]) > now and not r.get("excluded_reason")],
            "results": list(reversed(results))[:1000], "performance": metrics,
            "performance_subgroups": quality_report,
            "history": {"matches": len(history), "start": min((m.scheduled_at for m in history), default=now).isoformat(),
                        "end": max((m.scheduled_at for m in history), default=now).isoformat()}}
