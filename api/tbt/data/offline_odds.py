from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


def _ascii(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def norm_text(value: object) -> str:
    text = _ascii(value).lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def norm_surface(value: object) -> str:
    text = norm_text(value)
    for surface in ("clay", "grass", "hard", "carpet"):
        if surface in text:
            return surface
    return text or "unknown"


def norm_round(value: object) -> str:
    text = norm_text(value)
    aliases = {
        "the final": "f", "final": "f", "f": "f",
        "semifinals": "sf", "semifinal": "sf", "semi finals": "sf", "sf": "sf",
        "quarterfinals": "qf", "quarterfinal": "qf", "quarter finals": "qf", "qf": "qf",
        "round of 16": "r16", "r16": "r16",
        "round of 32": "r32", "r32": "r32",
        "round of 64": "r64", "r64": "r64",
        "round of 128": "r128", "r128": "r128",
    }
    return aliases.get(text, text)


def parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "null", "nat"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def decimal_odds(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or not 1.0 < result <= 1000.0:
        return None
    return result


def fair_market(player1_odds: float, player2_odds: float) -> dict[str, float]:
    raw1, raw2 = 1.0 / player1_odds, 1.0 / player2_odds
    total = raw1 + raw2
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Invalid two-way market")
    return {
        "player1_implied_probability": raw1 / total,
        "player2_implied_probability": raw2 / total,
        "raw_overround": total - 1.0,
    }


def _legacy_name_parts(value: object) -> tuple[tuple[str, ...], str]:
    tokens = norm_text(value).split()
    if not tokens:
        return (), ""
    cut = len(tokens)
    while cut > 0 and len(tokens[cut - 1]) == 1 and tokens[cut - 1].isalpha():
        cut -= 1
    if cut == len(tokens):
        return tuple(tokens), ""
    surname = tuple(tokens[:cut])
    initials = "".join(tokens[cut:])
    return surname, initials


def legacy_name_matches(legacy: object, canonical: object) -> bool:
    legacy_norm = norm_text(legacy)
    canonical_norm = norm_text(canonical)
    if not legacy_norm or not canonical_norm:
        return False
    if legacy_norm == canonical_norm:
        return True

    surname, initials = _legacy_name_parts(legacy)
    tokens = canonical_norm.split()
    if not surname or not initials or len(tokens) <= len(surname):
        return False

    n = len(surname)
    if tuple(tokens[-n:]) == surname:
        given = tokens[:-n]
        canonical_initials = "".join(part[0] for part in given if part)
        if canonical_initials.startswith(initials):
            return True
    if tuple(tokens[:n]) == surname:
        given = tokens[n:]
        canonical_initials = "".join(part[0] for part in given if part)
        if canonical_initials.startswith(initials):
            return True
    return False


def pair_orientation(
    source_a: object,
    source_b: object,
    canonical_1: object,
    canonical_2: object,
) -> str | None:
    direct = legacy_name_matches(source_a, canonical_1) and legacy_name_matches(source_b, canonical_2)
    swapped = legacy_name_matches(source_a, canonical_2) and legacy_name_matches(source_b, canonical_1)
    if direct == swapped:
        return None
    return "direct" if direct else "swapped"


def tournament_score(source: object, canonical: object) -> tuple[int, str]:
    left, right = norm_text(source), norm_text(canonical)
    if not left or not right:
        return 0, "tournament_missing"
    if left == right:
        return 2, "tournament_exact"
    lt, rt = set(left.split()), set(right.split())
    overlap = len(lt & rt) / max(1, min(len(lt), len(rt)))
    if overlap >= 0.67:
        return 1, "tournament_tokens"
    return 0, "tournament_mismatch"


def round_evidence(source: object, canonical: object) -> tuple[int, str]:
    left, right = norm_round(source), norm_round(canonical)
    if not left or not right:
        return 0, "round_missing"
    decisive = {"f", "sf", "qf", "r16", "r32", "r64", "r128"}
    if left == right:
        return 1, "round"
    if left in decisive and right in decisive:
        return -100, "round_conflict"
    return 0, "round_unmapped"


def source_match_id(*parts: object) -> str:
    raw = "|".join(norm_text(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class LegacyOddsRow:
    row_number: int
    tour: str
    event_date: date
    tournament: str
    surface: str
    round_name: str
    best_of: int | None
    player_a: str
    player_b: str
    winner: str
    rank_a: int | None
    rank_b: int | None
    odds_a: float
    odds_b: float
    source_match_id: str


def int_or_none(value: object) -> int | None:
    try:
        result = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def parse_legacy_row(
    row: dict[str, Any],
    *,
    row_number: int,
    tour: str,
) -> LegacyOddsRow | None:
    day = parse_date(row.get("Date") or row.get("date"))
    p1 = str(row.get("Player_1") or row.get("player_1") or "").strip()
    p2 = str(row.get("Player_2") or row.get("player_2") or "").strip()
    winner = str(row.get("Winner") or row.get("winner") or "").strip()
    o1 = decimal_odds(row.get("Odd_1") if "Odd_1" in row else row.get("odd_1"))
    o2 = decimal_odds(row.get("Odd_2") if "Odd_2" in row else row.get("odd_2"))
    if day is None or not p1 or not p2 or not winner or o1 is None or o2 is None:
        return None
    bo = int_or_none(row.get("Best of") if "Best of" in row else row.get("best_of"))
    if bo not in {3, 5}:
        bo = None
    tournament = str(row.get("Tournament") or row.get("tournament") or "").strip()
    surface = norm_surface(row.get("Surface") or row.get("surface"))
    round_name = str(row.get("Round") or row.get("round") or "").strip()
    rid = source_match_id(tour, day.isoformat(), tournament, p1, p2, winner, o1, o2)
    return LegacyOddsRow(
        row_number=row_number,
        tour=str(tour or "").lower(),
        event_date=day,
        tournament=tournament,
        surface=surface,
        round_name=round_name,
        best_of=bo,
        player_a=p1,
        player_b=p2,
        winner=winner,
        rank_a=int_or_none(row.get("Rank_1") if "Rank_1" in row else row.get("rank_1")),
        rank_b=int_or_none(row.get("Rank_2") if "Rank_2" in row else row.get("rank_2")),
        odds_a=o1,
        odds_b=o2,
        source_match_id=rid,
    )


def candidate_link(
    source: LegacyOddsRow,
    *,
    canonical_tour: object,
    canonical_date: date,
    canonical_player1: object,
    canonical_player2: object,
    canonical_winner: object,
    canonical_tournament: object,
    canonical_surface: object,
    canonical_round: object,
    canonical_best_of: int | None,
    canonical_rank1: int | None = None,
    canonical_rank2: int | None = None,
) -> dict[str, Any]:
    evidence: list[str] = []
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
    evidence.append("date_exact" if delta == 0 else "date_plusminus_1")

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

    rscore, revidence = round_evidence(source.round_name, canonical_round)
    if rscore < 0:
        return {"accepted": False, "score": score, "evidence": evidence + [revidence]}
    score += rscore
    evidence.append(revidence)

    if source.best_of and canonical_best_of:
        if int(source.best_of) != int(canonical_best_of):
            return {"accepted": False, "score": score, "evidence": evidence + ["best_of_conflict"]}
        score += 1
        evidence.append("best_of")

    if orientation == "direct":
        source_ranks = (source.rank_a, source.rank_b)
        target_ranks = (canonical_rank1, canonical_rank2)
        p1_odds, p2_odds = source.odds_a, source.odds_b
    else:
        source_ranks = (source.rank_b, source.rank_a)
        target_ranks = (canonical_rank1, canonical_rank2)
        p1_odds, p2_odds = source.odds_b, source.odds_a

    rank_known = all(value is not None for value in (*source_ranks, *target_ranks))
    if rank_known:
        diffs = [abs(int(a) - int(b)) for a, b in zip(source_ranks, target_ranks)]
        if max(diffs) == 0:
            score += 2
            evidence.append("ranks_exact")
        elif max(diffs) <= 2:
            score += 1
            evidence.append("ranks_close")
        else:
            evidence.append("ranks_different")

    if delta == 0:
        accepted = score >= 9
    else:
        accepted = (
            score >= 9
            and "tournament_exact" in evidence
            and "round" in evidence
            and (not source.best_of or not canonical_best_of or "best_of" in evidence)
        )

    market = fair_market(p1_odds, p2_odds)
    market.update({"player1_odds": p1_odds, "player2_odds": p2_odds})
    return {
        "accepted": accepted,
        "score": score,
        "evidence": evidence,
        "orientation": orientation,
        "market": market,
    }


MARKET_MARKER_FIELDS = (
    "schema", "status", "source", "source_match_id", "source_file_sha256",
    "price_kind", "player1_odds", "player2_odds",
    "player1_implied_probability", "player2_implied_probability", "raw_overround",
)


def build_market_marker(
    market: dict[str, float],
    *,
    source: str,
    source_match_id_value: str,
    source_file_sha256: str = "",
) -> dict[str, Any]:
    marker: dict[str, Any] = {
        "schema": 1,
        "status": "linked",
        "source": str(source),
        "source_match_id": str(source_match_id_value),
        "price_kind": "historical_two_way_unspecified_timestamp",
        "player1_odds": float(market["player1_odds"]),
        "player2_odds": float(market["player2_odds"]),
        "player1_implied_probability": float(market["player1_implied_probability"]),
        "player2_implied_probability": float(market["player2_implied_probability"]),
        "raw_overround": float(market["raw_overround"]),
    }
    if source_file_sha256:
        marker["source_file_sha256"] = str(source_file_sha256)
    return marker


def clean_market_marker(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("status") != "linked":
        return None
    if value.get("price_kind") != "historical_two_way_unspecified_timestamp":
        return None
    o1 = decimal_odds(value.get("player1_odds"))
    o2 = decimal_odds(value.get("player2_odds"))
    if o1 is None or o2 is None:
        return None
    fair = fair_market(o1, o2)
    for key in ("player1_implied_probability", "player2_implied_probability", "raw_overround"):
        try:
            observed = float(value.get(key))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(observed) or abs(observed - fair[key]) > 1e-9:
            return None
    source = str(value.get("source") or "").strip()
    sid = str(value.get("source_match_id") or "").strip()
    if not source or not sid:
        return None
    return build_market_marker(
        {**fair, "player1_odds": o1, "player2_odds": o2},
        source=source,
        source_match_id_value=sid,
        source_file_sha256=str(value.get("source_file_sha256") or "").strip(),
    )


def market_marker_equivalent(left: Any, right: Any) -> bool:
    clean_left = clean_market_marker(left)
    clean_right = clean_market_marker(right)
    return clean_left is not None and clean_left == clean_right
