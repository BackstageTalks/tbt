from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Iterable

from .offline_odds import norm_surface, norm_text, pair_orientation


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


def american_to_decimal(value: object) -> float | None:
    try:
        price = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price == 0:
        return None
    result = 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / abs(price)
    if not math.isfinite(result) or not 1.0 < result <= 1000.0:
        return None
    return float(result)


def fair_market(player1_decimal: float, player2_decimal: float) -> dict[str, float]:
    raw1, raw2 = 1.0 / player1_decimal, 1.0 / player2_decimal
    total = raw1 + raw2
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Invalid two-way market")
    return {
        "player1_fair_probability": raw1 / total,
        "player2_fair_probability": raw2 / total,
        "raw_overround": total - 1.0,
    }


@dataclass(frozen=True)
class TournamentMeta:
    start_date: date
    end_date: date
    tournament: str
    surface: str
    location: str
    masters: int | None


@dataclass(frozen=True)
class BookQuote:
    book_id: str
    book_name: str
    betting_date: date
    player_a: str
    player_b: str
    player_a_decimal: float
    player_b_decimal: float
    player_a_fair_probability: float
    player_b_fair_probability: float
    raw_overround: float
    row_number: int


@dataclass(frozen=True)
class SourceMoneylineMatch:
    source_match_id: str
    tournament: TournamentMeta
    match_date: date
    player_a: str
    player_b: str
    quotes: tuple[BookQuote, ...]


def parse_tournament_row(row: dict[str, Any]) -> TournamentMeta | None:
    start = parse_date(row.get("start_date"))
    end = parse_date(row.get("end_date"))
    tournament = str(row.get("tournament") or "").strip()
    if start is None or end is None or end < start or not tournament:
        return None
    try:
        masters = int(float(str(row.get("masters") or "").strip()))
    except (TypeError, ValueError):
        masters = None
    return TournamentMeta(
        start_date=start,
        end_date=end,
        tournament=tournament,
        surface=norm_surface(row.get("court_surface")),
        location=str(row.get("location") or "").strip(),
        masters=masters,
    )


def _same_implied_probability(raw: object, expected: float) -> bool:
    if raw in (None, ""):
        return True
    try:
        observed = float(raw)
    except (TypeError, ValueError):
        return False
    return math.isfinite(observed) and abs(observed - expected) <= 1e-8


def parse_moneyline_row(
    row: dict[str, Any],
    *,
    row_number: int,
    tournament: TournamentMeta,
) -> BookQuote | None:
    start = parse_date(row.get("start_date"))
    betting_date = parse_date(row.get("betting_date"))
    source_tournament = str(row.get("tournament") or "").strip()
    team1 = str(row.get("team1") or "").strip()
    team2 = str(row.get("team2") or "").strip()
    if (
        start != tournament.start_date
        or betting_date is None
        or norm_text(source_tournament) != norm_text(tournament.tournament)
        or not team1
        or not team2
        or norm_text(team1) == norm_text(team2)
        or "_" in team1
        or "_" in team2
    ):
        return None

    d1 = american_to_decimal(row.get("price1"))
    d2 = american_to_decimal(row.get("price2"))
    if d1 is None or d2 is None:
        return None
    if not _same_implied_probability(row.get("odds1"), 1.0 / d1):
        return None
    if not _same_implied_probability(row.get("odds2"), 1.0 / d2):
        return None

    fair = fair_market(d1, d2)
    if norm_text(team1) <= norm_text(team2):
        player_a, player_b = team1, team2
        a_decimal, b_decimal = d1, d2
        a_fair, b_fair = fair["player1_fair_probability"], fair["player2_fair_probability"]
    else:
        player_a, player_b = team2, team1
        a_decimal, b_decimal = d2, d1
        a_fair, b_fair = fair["player2_fair_probability"], fair["player1_fair_probability"]

    return BookQuote(
        book_id=str(row.get("book_id") or "").strip(),
        book_name=str(row.get("book_name") or "").strip() or "unknown",
        betting_date=betting_date,
        player_a=player_a,
        player_b=player_b,
        player_a_decimal=float(a_decimal),
        player_b_decimal=float(b_decimal),
        player_a_fair_probability=float(a_fair),
        player_b_fair_probability=float(b_fair),
        raw_overround=float(fair["raw_overround"]),
        row_number=int(row_number),
    )


def safe_group_match_date(
    quotes: Iterable[BookQuote],
    tournament: TournamentMeta,
) -> date | None:
    in_window = {
        quote.betting_date
        for quote in quotes
        if tournament.start_date <= quote.betting_date <= tournament.end_date
    }
    return next(iter(in_window)) if len(in_window) == 1 else None


def source_match_id(
    *,
    tournament: TournamentMeta,
    match_date: date,
    player_a: str,
    player_b: str,
) -> str:
    import hashlib

    raw = "|".join(
        (
            tournament.start_date.isoformat(),
            norm_text(tournament.tournament),
            match_date.isoformat(),
            norm_text(player_a),
            norm_text(player_b),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def candidate_link(
    source: SourceMoneylineMatch,
    *,
    canonical_date: date,
    canonical_player1: object,
    canonical_player2: object,
    canonical_tournament: object,
    canonical_surface: object,
) -> dict[str, Any]:
    orientation = pair_orientation(
        source.player_a,
        source.player_b,
        canonical_player1,
        canonical_player2,
    )
    if orientation is None:
        return {"accepted": False, "score": -100, "evidence": ["pair_mismatch_or_ambiguous"]}
    if canonical_date != source.match_date:
        return {"accepted": False, "score": -100, "evidence": ["match_date_mismatch"]}
    if norm_text(source.tournament.tournament) != norm_text(canonical_tournament):
        return {"accepted": False, "score": -100, "evidence": ["tournament_mismatch"]}

    evidence = ["pair", "match_date_exact", "tournament_exact"]
    source_surface = norm_surface(source.tournament.surface)
    target_surface = norm_surface(canonical_surface)
    if source_surface not in {"", "unknown"} and target_surface not in {"", "unknown"}:
        if source_surface != target_surface:
            return {"accepted": False, "score": -100, "evidence": evidence + ["surface_conflict"]}
        evidence.append("surface")

    return {
        "accepted": True,
        "score": 10 + (1 if "surface" in evidence else 0),
        "evidence": evidence,
        "orientation": orientation,
    }


def _orient_quote(quote: BookQuote, orientation: str) -> dict[str, Any]:
    if orientation == "direct":
        p1d, p2d = quote.player_a_decimal, quote.player_b_decimal
        p1f, p2f = quote.player_a_fair_probability, quote.player_b_fair_probability
    else:
        p1d, p2d = quote.player_b_decimal, quote.player_a_decimal
        p1f, p2f = quote.player_b_fair_probability, quote.player_a_fair_probability
    return {
        "book_id": quote.book_id,
        "book_name": quote.book_name,
        "betting_date": quote.betting_date.isoformat(),
        "player1_decimal_odds": float(p1d),
        "player2_decimal_odds": float(p2d),
        "player1_fair_probability": float(p1f),
        "player2_fair_probability": float(p2f),
        "raw_overround": float(quote.raw_overround),
    }


def _book_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("book_id") or ""), norm_text(item.get("book_name"))


def build_market_sidecar(
    source: SourceMoneylineMatch,
    *,
    orientation: str,
    source_label: str,
    source_file_sha256: str,
) -> dict[str, Any]:
    quotes = [
        _orient_quote(quote, orientation)
        for quote in source.quotes
        if quote.betting_date == source.match_date
    ]

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in quotes:
        key = _book_key(item)
        if key not in deduped:
            deduped[key] = item
    quotes = sorted(
        deduped.values(),
        key=lambda item: (norm_text(item["book_name"]), str(item["book_id"])),
    )

    real_books = [
        item
        for item in quotes
        if str(item["book_id"]) != "-1" and norm_text(item["book_name"]) != "oddsportal"
    ]
    consensus_quotes = real_books if real_books else quotes
    if not consensus_quotes:
        raise ValueError("No valid source quotes")

    p1_fair = float(
        median(float(item["player1_fair_probability"]) for item in consensus_quotes)
    )
    median_overround = float(
        median(float(item["raw_overround"]) for item in consensus_quotes)
    )

    return {
        "schema": 1,
        "status": "linked",
        "source": str(source_label),
        "source_match_id": source.source_match_id,
        "source_file_sha256": str(source_file_sha256),
        "price_kind": "historical_moneyline_unspecified_quote_time",
        "betting_date_semantics": "source_reported_match_or_record_date_not_capture_timestamp",
        "model_feature_policy": "benchmark_only_no_training_feature",
        "match_date": source.match_date.isoformat(),
        "tournament_start_date": source.tournament.start_date.isoformat(),
        "tournament_end_date": source.tournament.end_date.isoformat(),
        "surface": source.tournament.surface,
        "location": source.tournament.location,
        "masters": source.tournament.masters,
        "bookmaker_count": len(real_books),
        "source_quote_count": len(quotes),
        "consensus": {
            "method": "median_no_vig_probability_real_bookmakers_else_all_sources",
            "player1_fair_probability": p1_fair,
            "player2_fair_probability": 1.0 - p1_fair,
            "median_raw_overround": median_overround,
        },
        "quotes": quotes,
    }
