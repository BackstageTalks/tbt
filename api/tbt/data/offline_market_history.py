from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .offline_odds import (
    decimal_odds,
    fair_market,
    legacy_name_matches,
    norm_surface,
    norm_text,
    pair_orientation,
    tournament_score,
)


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _int(value: object) -> int | None:
    try:
        result = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return result


def _market(left: object, right: object) -> dict[str, float] | None:
    o1, o2 = decimal_odds(left), decimal_odds(right)
    if o1 is None or o2 is None:
        return None
    fair = fair_market(o1, o2)
    return {
        "player1_odds": float(o1),
        "player2_odds": float(o2),
        **{key: float(value) for key, value in fair.items()},
    }


@dataclass(frozen=True)
class ValuebetMarketRow:
    row_number: int
    source_match_id: str
    tour: str
    event_date: date
    tournament: str
    tournament_id: str
    category: str
    surface: str
    round_number: int | None
    player_a: str
    player_a_id: str
    player_b: str
    player_b_id: str
    winner: str
    opening: dict[str, float] | None
    closing: dict[str, float] | None


def parse_valuebet_row(row: dict[str, Any], *, row_number: int) -> ValuebetMarketRow | None:
    played_at = _parse_datetime(row.get("date"))
    tour = norm_text(row.get("genre"))
    if played_at is None or tour not in {"atp", "wta"}:
        return None

    p1 = str(row.get("joueur1") or "").strip()
    p2 = str(row.get("joueur2") or "").strip()
    p1_id = str(row.get("joueur1_id") or "").strip()
    p2_id = str(row.get("joueur2_id") or "").strip()
    winner_id = str(row.get("vainqueur_id") or "").strip()
    if not p1 or not p2 or not p1_id or not p2_id or winner_id not in {p1_id, p2_id}:
        return None

    opening = _market(row.get("cote1_ouverture"), row.get("cote2_ouverture"))
    closing = _market(row.get("cote1_cloture"), row.get("cote2_cloture"))
    if opening is None and closing is None:
        return None

    raw_id = str(row.get("match_id") or "").strip()
    if raw_id:
        source_id = raw_id
    else:
        seed = "|".join(
            (
                tour,
                played_at.date().isoformat(),
                norm_text(row.get("tournoi")),
                norm_text(p1),
                norm_text(p2),
            )
        )
        source_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]

    return ValuebetMarketRow(
        row_number=row_number,
        source_match_id=source_id,
        tour=tour,
        event_date=played_at.date(),
        tournament=str(row.get("tournoi") or "").strip(),
        tournament_id=str(row.get("tournoi_id") or "").strip(),
        category=str(row.get("categorie") or "").strip(),
        surface=norm_surface(row.get("surface")),
        round_number=_int(row.get("tour")),
        player_a=p1,
        player_a_id=p1_id,
        player_b=p2,
        player_b_id=p2_id,
        winner=p1 if winner_id == p1_id else p2,
        opening=opening,
        closing=closing,
    )


def _round_bucket(value: int | None) -> str:
    return {
        12: "f",
        11: "sf",
        10: "qf",
        9: "r16",
        8: "r32",
        7: "r64",
        6: "r128",
    }.get(value, "")


def _canonical_round(value: object) -> str:
    text = norm_text(value)
    aliases = {
        "final": "f",
        "finals": "f",
        "f": "f",
        "semifinal": "sf",
        "semifinals": "sf",
        "semi final": "sf",
        "semi finals": "sf",
        "sf": "sf",
        "quarterfinal": "qf",
        "quarterfinals": "qf",
        "quarter final": "qf",
        "quarter finals": "qf",
        "qf": "qf",
        "round of 16": "r16",
        "r16": "r16",
        "round of 32": "r32",
        "r32": "r32",
        "round of 64": "r64",
        "r64": "r64",
        "round of 128": "r128",
        "r128": "r128",
    }
    return aliases.get(text, "")


def candidate_link(
    source: ValuebetMarketRow,
    *,
    canonical_tour: object,
    canonical_date: date,
    canonical_player1: object,
    canonical_player2: object,
    canonical_winner: object,
    canonical_tournament: object,
    canonical_surface: object,
    canonical_round: object,
) -> dict[str, Any]:
    if source.tour != norm_text(canonical_tour):
        return {"accepted": False, "score": -100, "evidence": ["tour_mismatch"]}

    orientation = pair_orientation(
        source.player_a,
        source.player_b,
        canonical_player1,
        canonical_player2,
    )
    if orientation is None:
        return {"accepted": False, "score": -100, "evidence": ["pair_mismatch_or_ambiguous"]}

    delta = abs((canonical_date - source.event_date).days)
    if delta > 1:
        return {"accepted": False, "score": -100, "evidence": ["date_mismatch"]}
    score = 4 if delta == 0 else 1
    evidence = ["date_exact" if delta == 0 else "date_plusminus_1"]

    if not canonical_winner or not legacy_name_matches(source.winner, canonical_winner):
        return {"accepted": False, "score": score, "evidence": evidence + ["winner_conflict"]}
    score += 3
    evidence.append("winner")

    source_surface = norm_surface(source.surface)
    target_surface = norm_surface(canonical_surface)
    if source_surface not in {"", "unknown"} and target_surface not in {"", "unknown"}:
        if source_surface != target_surface:
            return {"accepted": False, "score": score, "evidence": evidence + ["surface_conflict"]}
        score += 1
        evidence.append("surface")

    tscore, tevidence = tournament_score(source.tournament, canonical_tournament)
    if tscore <= 0:
        return {"accepted": False, "score": score, "evidence": evidence + [tevidence]}
    score += tscore
    evidence.append(tevidence)

    sr, cr = _round_bucket(source.round_number), _canonical_round(canonical_round)
    if sr and cr:
        if sr != cr:
            return {"accepted": False, "score": score, "evidence": evidence + ["round_conflict"]}
        score += 1
        evidence.append("round")

    if delta == 0:
        accepted = score >= 9
    else:
        accepted = score >= 8 and tevidence == "tournament_exact" and "round" in evidence

    def orient_market(value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return None
        if orientation == "direct":
            return dict(value)
        return {
            "player1_odds": value["player2_odds"],
            "player2_odds": value["player1_odds"],
            "player1_implied_probability": value["player2_implied_probability"],
            "player2_implied_probability": value["player1_implied_probability"],
            "raw_overround": value["raw_overround"],
        }

    return {
        "accepted": accepted,
        "score": score,
        "evidence": evidence,
        "orientation": orientation,
        "opening": orient_market(source.opening),
        "closing": orient_market(source.closing),
    }


def build_market_history_marker(
    *,
    source: ValuebetMarketRow,
    linked: dict[str, Any],
    source_label: str,
    source_file_sha256: str,
) -> dict[str, Any]:
    marker: dict[str, Any] = {
        "schema": 1,
        "status": "linked",
        "source": str(source_label),
        "source_match_id": str(source.source_match_id),
        "source_file_sha256": str(source_file_sha256),
        "price_kind": "historical_open_close",
        "closing_semantics": "last_recorded_before_match",
        "model_feature_policy": "opening_only_candidate; closing_validation_only",
    }
    if linked.get("opening") is not None:
        marker["opening"] = linked["opening"]
    if linked.get("closing") is not None:
        marker["closing"] = linked["closing"]
    return marker


def clean_market_history_marker(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("schema") != 1 or value.get("status") != "linked":
        return None
    if value.get("price_kind") != "historical_open_close":
        return None
    if value.get("closing_semantics") != "last_recorded_before_match":
        return None
    if value.get("model_feature_policy") != "opening_only_candidate; closing_validation_only":
        return None
    source = str(value.get("source") or "").strip()
    source_match_id = str(value.get("source_match_id") or "").strip()
    source_sha = str(value.get("source_file_sha256") or "").strip()
    if not source or not source_match_id or not source_sha:
        return None

    cleaned = {
        "schema": 1,
        "status": "linked",
        "source": source,
        "source_match_id": source_match_id,
        "source_file_sha256": source_sha,
        "price_kind": "historical_open_close",
        "closing_semantics": "last_recorded_before_match",
        "model_feature_policy": "opening_only_candidate; closing_validation_only",
    }
    for kind in ("opening", "closing"):
        market = value.get(kind)
        if market is None:
            continue
        if not isinstance(market, dict):
            return None
        o1 = decimal_odds(market.get("player1_odds"))
        o2 = decimal_odds(market.get("player2_odds"))
        if o1 is None or o2 is None:
            return None
        fair = fair_market(o1, o2)
        observed = {
            "player1_odds": float(o1),
            "player2_odds": float(o2),
            **{key: float(fair[key]) for key in fair},
        }
        for key, expected in observed.items():
            try:
                actual = float(market.get(key))
            except (TypeError, ValueError):
                return None
            if not math.isfinite(actual) or abs(actual - expected) > 1e-9:
                return None
        cleaned[kind] = observed
    if "opening" not in cleaned and "closing" not in cleaned:
        return None
    return cleaned


def market_history_equivalent(left: Any, right: Any) -> bool:
    a = clean_market_history_marker(left)
    b = clean_market_history_marker(right)
    return a is not None and a == b
