"""Offline prediction publication with immutable pre-match records."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import json
import numpy as np
import pandas as pd

from ..models.feature_builder import FeatureBuilder, FEATURE_NAMES
from ..models.metrics import evaluate_probabilities
from .prediction_quality import coverage, subgroup_report
from .data_quality import audit_history
from .training import _enforce_rank_provenance
from .publication import confirm_publication


def event_id(match):
    raw = match.provider_payload or {}
    return str(next((raw.get(k) for k in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id") if raw.get(k)), match.match_id))


def _provider_player_country(payload, *, player1):
    """Best-effort ISO-2 country extraction from TennisApi event payload."""
    if not isinstance(payload, dict):
        return ""
    keys = ("homeTeam", "home_team", "player1", "participant1", "player_1") if player1 else ("awayTeam", "away_team", "player2", "participant2", "player_2")
    side = next((payload.get(k) for k in keys if isinstance(payload.get(k), dict)), {})
    candidates = []
    if isinstance(side, dict):
        candidates.extend([side.get("country_code"), side.get("countryCode"), side.get("countryAlpha2"), side.get("country_code2")])
        country = side.get("country")
        if isinstance(country, dict):
            candidates.extend([country.get("alpha2"), country.get("code"), country.get("iso2"), country.get("countryCode")])
    for value in candidates:
        text = str(value or "").strip().upper()
        if len(text) == 2 and text.isalpha():
            return text
    return ""


def _recent_form_summary(state, *, surface=None, limit=10):
    """Point-in-time recent form for presentation only.

    The builder has only been replayed with matches strictly before the prediction
    cutoff, so these summaries cannot include the event being predicted.
    """
    rows = list(state.recent)
    if surface and surface != "unknown":
        rows = [item for item in rows if item.surface == surface]
    rows = rows[-max(1, int(limit)):]
    if not rows:
        return {"matches": 0, "wins": 0, "win_pct": None, "sequence": []}
    sequence = ["W" if float(item.won) >= 0.5 else "L" for item in rows]
    wins = sum(1 for value in sequence if value == "W")
    return {
        "matches": len(rows),
        "wins": wins,
        "win_pct": wins / len(rows),
        "sequence": sequence,
    }


def _h2h_record(builder, match):
    key1 = builder.player_key(match.tour, match.player1_id)
    key2 = builder.player_key(match.tour, match.player2_id)
    left, right = sorted((key1, key2))
    wins_left, wins_right = builder.h2h[(left, right)]
    if key1 == left:
        return int(wins_left), int(wins_right)
    return int(wins_right), int(wins_left)


def _presentation_player_profile(builder, match, *, player1):
    state = builder._state(match, player1)
    overall = _recent_form_summary(state, limit=10)
    surface = _recent_form_summary(state, surface=match.surface, limit=10)
    return {
        "history_matches": int(state.matches),
        "surface_history_matches": int(state.surface_matches.get(match.surface, 0)),
        "recent_form": overall,
        "surface_form": surface,
        "meaning": "point_in_time_recent_results_not_model_probability",
    }


def predict(model, history, upcoming, now=None):
    now = now or datetime.now(timezone.utc)
    # Match completion timestamps are unavailable. Use previous UTC days only,
    # matching the conservative whole-day training protocol. Validate the exact
    # replay slice with the same history/ranking policy used by training/backtest.
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    replay_history = [match for match in history if match.scheduled_at < cutoff]
    replay_history, _ = audit_history(replay_history, now=now)
    replay_history, _ = _enforce_rank_provenance(replay_history)
    builder = FeatureBuilder()
    builder.replay(replay_history, before=cutoff)
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
        tournament_obj = match.provider_payload.get("tournament") if isinstance(match.provider_payload, dict) else None
        unique_tournament = tournament_obj.get("uniqueTournament") if isinstance(tournament_obj, dict) else None
        tournament_logo_id = ""
        if isinstance(unique_tournament, dict):
            tournament_logo_id = str(unique_tournament.get("id") or "").strip()
        tournament_logo_id = tournament_logo_id or str(match.tournament_id or "")
        h2h_p1, h2h_p2 = _h2h_record(builder, match)
        profile1 = _presentation_player_profile(builder, match, player1=True)
        profile2 = _presentation_player_profile(builder, match, player1=False)
        profile1["h2h_wins"] = h2h_p1
        profile1["h2h_losses"] = h2h_p2
        profile2["h2h_wins"] = h2h_p2
        profile2["h2h_losses"] = h2h_p1
        rows.append({"id": match.match_id, "event_id": event_id(match), "tour": match.tour.upper(),
            "scheduled_at": match.scheduled_at.isoformat(), "tournament": match.tournament,
            "tournament_id": str(match.tournament_id or ""),
            "tournament_logo_id": tournament_logo_id,
            "surface": match.surface, "round": match.round_name,
            "best_of": match.best_of,
            "competition": match.tournament_level or "unknown", "quality": coverage(builder, match),
            "player1": {
                "id": match.player1_id, "name": match.player1_name,
                "probability": p, "rank": match.player1_rank,
                "country_code": _provider_player_country(match.provider_payload, player1=True),
                "photo_url": f"/api/v1/player-image/{match.player1_id}" if str(match.player1_id or "").isdigit() else "",
                "presentation": profile1,
            },
            "player2": {
                "id": match.player2_id, "name": match.player2_name,
                "probability": 1 - p, "rank": match.player2_rank,
                "country_code": _provider_player_country(match.provider_payload, player1=False),
                "photo_url": f"/api/v1/player-image/{match.player2_id}" if str(match.player2_id or "").isdigit() else "",
                "presentation": profile2,
            },
            "winner_id": winner, "confidence": max(p, 1 - p),
            "raw_model_confidence": max(p, 1 - p),
            "blinq_probability": 0.5 + (max(p, 1 - p) - 0.5) * float(f["data_depth"]),
            "probability_reliability": float(f["data_depth"]),
            "data_depth": f["data_depth"],
            "stats_available": bool(f["stats_known_both"]), "signals": signals,
            "model_version": model.version, "created_at": now.isoformat(),
            "issued_at": None, "publication_status": "pending", "result": None})
    return rows



def _publication_key(value):
    if not isinstance(value, dict):
        return ""
    return str(value.get("publication_key") or "").strip()


def _merge_market_publication_candidates(existing, candidate_row):
    """Merge independent betting-section publication candidates into a ledger row.

    Issued records are immutable. Pending records may be refreshed before a
    successful deployment, because no public betting commitment exists yet.
    """
    current = [dict(item) for item in existing.get("market_publications", []) if isinstance(item, dict)]
    by_key = {_publication_key(item): item for item in current if _publication_key(item)}
    for source in candidate_row.get("market_publication_candidates", []) or []:
        if not isinstance(source, dict):
            continue
        key = _publication_key(source)
        if not key:
            continue
        prior = by_key.get(key)
        if prior is None:
            item = dict(source)
            current.append(item)
            by_key[key] = item
            continue
        if prior.get("issued_at") or prior.get("publication_status") == "published":
            continue
        # No successful public deployment has committed this section yet, so
        # replace the stale pending snapshot with the current one.
        preserved_result = prior.get("result")
        prior.clear()
        prior.update(dict(source))
        if preserved_result is not None:
            prior["result"] = preserved_result
    existing["market_publications"] = current
    existing.pop("market_publication_candidates", None)


def _settle_match_winner_publications(row, match, now):
    publications = row.get("market_publications")
    if not isinstance(publications, list):
        return
    for publication in publications:
        if not isinstance(publication, dict) or publication.get("market") != "match_winner":
            continue
        issued_at = publication.get("issued_at")
        if not issued_at:
            continue
        try:
            issued = datetime.fromisoformat(str(issued_at).replace("Z", "+00:00"))
        except ValueError:
            publication["excluded_reason"] = "invalid_issued_at"
            continue
        if issued.tzinfo is None:
            publication["excluded_reason"] = "invalid_issued_at"
            continue
        if issued >= match.scheduled_at:
            publication["excluded_reason"] = "issued_after_actual_start"
            continue
        publication.pop("excluded_reason", None)
        selection_id = str(publication.get("selection_id") or "")
        correct = selection_id == str(match.winner_id or "")
        try:
            odds = float(publication.get("odds"))
        except (TypeError, ValueError):
            odds = 0.0
        if not np.isfinite(odds) or odds <= 1:
            publication["excluded_reason"] = "invalid_odds"
            continue
        profit_units = (odds - 1.0) if correct else -1.0
        existing = publication.get("result") if isinstance(publication.get("result"), dict) else None
        settled = {
            "winner_id": match.winner_id,
            "correct": correct,
            "staked_units": 1.0,
            "return_units": odds if correct else 0.0,
            "profit_units": profit_units,
            "settled_at": (existing or {}).get("settled_at") or now.isoformat(),
            "scheduled_at": match.scheduled_at.isoformat(),
        }
        if existing is not None and (
            existing.get("winner_id") != match.winner_id
            or existing.get("correct") != correct
            or abs(float(existing.get("profit_units", profit_units)) - profit_units) > 1e-12
        ):
            settled["corrected_at"] = now.isoformat()
        publication["result"] = settled


def _betting_metrics(publications):
    rows = [p for p in publications if isinstance(p, dict) and isinstance(p.get("result"), dict) and not p.get("excluded_reason")]
    if not rows:
        return {
            "n": 0, "wins": 0, "losses": 0, "hit_rate": None,
            "avg_odds": None, "staked_units": 0.0, "profit_units": 0.0, "roi": None,
        }
    wins = sum(1 for p in rows if p["result"].get("correct") is True)
    losses = sum(1 for p in rows if p["result"].get("correct") is False)
    odds = [float(p.get("odds")) for p in rows if p.get("odds") is not None]
    staked = sum(float(p["result"].get("staked_units") or 0.0) for p in rows)
    profit = sum(float(p["result"].get("profit_units") or 0.0) for p in rows)
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "hit_rate": wins / len(rows) if rows else None,
        "avg_odds": sum(odds) / len(odds) if odds else None,
        "staked_units": staked,
        "profit_units": profit,
        "roi": profit / staked if staked > 0 else None,
    }


def betting_performance(results):
    """Aggregate settled, actually-issued betting selections with flat 1u stakes."""
    publications = []
    for row in results:
        for publication in row.get("market_publications", []) or []:
            if isinstance(publication, dict) and publication.get("issued_at"):
                publications.append(publication)

    # Overall counts each underlying selection only once even when the same bet
    # was published in multiple Daily / Prime / Value sections. Earliest public
    # publication is the canonical overall snapshot.
    unique = {}
    for publication in publications:
        key = str(publication.get("selection_key") or publication.get("publication_key") or "")
        if not key:
            continue
        prior = unique.get(key)
        if prior is None or str(publication.get("issued_at") or "") < str(prior.get("issued_at") or ""):
            unique[key] = publication

    sections = {}
    for section in ("top_daily", "prime", "value", "ace", "double_faults", "sets", "games"):
        sections[section] = _betting_metrics([p for p in publications if p.get("section") == section])
    markets = {}
    for market in sorted({str(p.get("market") or "") for p in publications if p.get("market")}):
        markets[market] = _betting_metrics([p for p in publications if p.get("market") == market])
    return {
        "schema": 1,
        "stake_model": "flat_1u",
        "overall": _betting_metrics(list(unique.values())),
        "sections": sections,
        "markets": markets,
    }

def reconcile_ledger(ledger, predictions, history, now=None):
    now = now or datetime.now(timezone.utc)
    stored = {row["event_id"]: deepcopy(row) for row in ledger}
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
        _merge_market_publication_candidates(existing, row)
        if existing.get("result") is None:
            # Safe fixture metadata may be filled after the original probability
            # commitment. This never changes the published winner probability.
            if existing.get("best_of") in (None, "") and row.get("best_of") in {3, 5}:
                existing["best_of"] = row.get("best_of")
            existing.setdefault("original_scheduled_at", existing["scheduled_at"])
            existing["scheduled_at"] = row["scheduled_at"]
    # Provider IDs are not sufficient evidence of identity. Keep all candidates
    # instead of silently accepting whichever history row happens to come last.
    completed = {}
    for match in history:
        if match.is_completed:
            completed.setdefault(event_id(match), []).append(match)
    for key, row in stored.items():
        candidates = completed.get(key, [])
        if not candidates:
            continue
        expected = {row["player1"]["id"], row["player2"]["id"]}
        identities_match = all(
            expected == {match.player1_id, match.player2_id}
            for match in candidates
        )
        outcomes = {(match.winner_id, match.scheduled_at) for match in candidates}
        if not identities_match or len(outcomes) != 1:
            reason = "player_identity_mismatch" if not identities_match else "conflicting_completed_results"
            conflict = {
                "reason": reason,
                "event_id": str(key),
                "expected_player_ids": sorted(expected),
                "candidates": [
                    {"match_id": match.match_id,
                     "player_ids": sorted({match.player1_id, match.player2_id}),
                     "winner_id": match.winner_id,
                     "scheduled_at": match.scheduled_at.isoformat()}
                    for match in candidates
                ],
            }
            row["settlement_quarantine"] = conflict
            print(json.dumps({"warning": "settlement_identity_quarantined", **conflict}), flush=True)
            # Preserve commitments and prior results for audit. Neither these
            # results nor this fixture may enter the public feed while ambiguous.
            continue
        match = candidates[0]
        row.pop("settlement_quarantine", None)

        # The provider may correct the actual start after settlement. Scheduled
        # time is mutable, but the published probability/issuance timestamp is not.
        row.setdefault("original_scheduled_at", row["scheduled_at"])
        row["scheduled_at"] = match.scheduled_at.isoformat()
        _settle_match_winner_publications(row, match, now)
        issued_at = row.get("issued_at")
        if not issued_at:
            # Pending predictions are never scored until a successful public
            # deployment confirms that they were actually available pre-match.
            continue

        existing_result = row.get("result")
        corrected_result = None
        if existing_result is not None:
            corrected_result = {
                **existing_result,
                "winner_id": match.winner_id,
                "correct": row["winner_id"] == match.winner_id,
                "scheduled_at": match.scheduled_at.isoformat(),
            }
            if (
                existing_result.get("winner_id") != match.winner_id
                or existing_result.get("correct")
                != (row["winner_id"] == match.winner_id)
            ):
                corrected_result["corrected_at"] = now.isoformat()

        if datetime.fromisoformat(issued_at) >= match.scheduled_at:
            row["excluded_reason"] = "issued_after_actual_start"
            if corrected_result is not None:
                row["result"] = corrected_result
            continue

        if row.get("excluded_reason") == "issued_after_actual_start":
            row.pop("excluded_reason", None)

        if corrected_result is not None:
            row["result"] = corrected_result
            continue

        row["result"] = {
            "winner_id": match.winner_id,
            "correct": row["winner_id"] == match.winner_id,
            "settled_at": now.isoformat(),
            "scheduled_at": match.scheduled_at.isoformat(),
        }
    return sorted(stored.values(), key=lambda r: r["scheduled_at"])




def serving_feed(ledger, model, history, report, upcoming, now=None):
    now = now or datetime.now(timezone.utc)
    future = {event_id(m) for m in upcoming if m.scheduled_at > now
              and not m.is_completed and m.status in {"upcoming", "notstarted", "scheduled"}}
    results = [row for row in ledger if row.get("result") is not None
               and not row.get("excluded_reason") and not row.get("settlement_quarantine")]
    metrics = evaluate_probabilities(
        [int(r["result"]["winner_id"] == r["player1"]["id"]) for r in results],
        [r["player1"]["probability"] for r in results]) if results else {}
    quality_frame = pd.DataFrame([{'target': int(r['result']['winner_id'] == r['player1']['id']),
        'tour': r['tour'], 'surface': r['surface'], 'competition': r.get('competition', 'unknown'),
        'tournament': r.get('tournament', 'unknown'),
        'history_band': r.get('quality', {}).get('history_band', 'unknown'),
        'surface_history_band': r.get('quality', {}).get('surface_history_band', 'unknown')} for r in results])
    quality_report = subgroup_report(quality_frame, [r['player1']['probability'] for r in results]) if results else {}
    betting = betting_performance(results)
    result_rows = list(reversed(results))[:1000]
    return {"schema": 1, "ready": True, "generated_at": now.isoformat(),
            "model": {"version": model.version, "report": report, "objective": "accuracy"},
            "upcoming": [r for r in ledger if r["event_id"] in future and r.get("result") is None
                         and datetime.fromisoformat(r["scheduled_at"]) > now
                         and not r.get("excluded_reason") and not r.get("settlement_quarantine")],
            "results": result_rows, "performance": metrics,
            "betting_performance": betting,
            "results_meta": {"settled_total": len(results), "returned": len(result_rows), "limit": 1000},
            "performance_subgroups": quality_report,
            "history": {"matches": len(history), "start": min((m.scheduled_at for m in history), default=now).isoformat(),
                        "end": max((m.scheduled_at for m in history), default=now).isoformat()}}
