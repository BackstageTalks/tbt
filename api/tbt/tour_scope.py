"""Forward-only paid-provider scope: ATP 250+ / WTA 250+ singles and doubles.

Source category IDs are TennisApi-native. Unknown or contradictory grades
fail closed for *new* collection; canonical historical records are never deleted.
"""
from __future__ import annotations

import re

_MAIN_CATEGORY = {"atp": 3, "wta": 6}
_SLAM_CATEGORY = -100
_BELOW_250_CATEGORY = {72, 213, 785, 871}  # Challenger, ITF W/M, WTA 125
_BELOW_250 = re.compile(
    r"\b(?:itf|futures?|challengers?|utr|juniors?|wheelchair|"
    r"exhibitions?|next[\s_-]*gen)\b|\b(?:atp|wta)[\s_-]*(?:15|25|35|50|60|75|80|100|110|125|150|175)\b",
    re.I,
)
_EXPLICIT_250_PLUS = re.compile(
    r"\b(?:atp|wta)[\s_-]*(?:250|500|1000|finals)\b|"
    r"\bmasters[\s_-]*1000\b|\bgrand[\s_-]*slams?\b|"
    r"\bwta[\s_-]*(?:international|premier(?:[\s_-]*(?:mandatory|5))?)\b",
    re.I,
)
_SLAMS = re.compile(
    r"\b(?:australian open|roland garros|french open|wimbledon|us open)\b",
    re.I,
)


def is_250_plus(tour: str, *, category_id=None, labels=()) -> bool:
    """Require a native main-tour ID or explicit event-grade evidence.

    Reject explicit lower-grade signals before any positive category evidence
    to handle mislabelled ATP/WTA cards and mixed provider payloads.
    """
    tour = str(tour or "").strip().casefold()
    if tour not in _MAIN_CATEGORY:
        return False
    try:
        category = int(category_id) if category_id not in (None, "") else None
    except (TypeError, ValueError):
        category = None
    text = " ".join(str(label or "") for label in labels).casefold()
    if category in _BELOW_250_CATEGORY or _BELOW_250.search(text):
        return False
    if category in set(_MAIN_CATEGORY.values()) and category != _MAIN_CATEGORY[tour]:
        return False
    if category == _MAIN_CATEGORY[tour] or category == _SLAM_CATEGORY:
        return True
    if _EXPLICIT_250_PLUS.search(text) or _SLAMS.search(text):
        return True
    return False


def match_is_250_plus(match) -> bool:
    """Eligibility for *new API requests*, using preserved native provenance."""
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    tournament = raw.get("tournament") if isinstance(raw.get("tournament"), dict) else {}
    category = tournament.get("category") if isinstance(tournament.get("category"), dict) else {}
    rank = tournament.get("rank") if isinstance(tournament.get("rank"), dict) else {}
    source_id = raw.get("_tbt_source_category_id")
    if source_id in (None, ""):
        source_id = category.get("id")
    labels = (
        match.tournament, match.tournament_level,
        raw.get("_tbt_source_category_name"),
        category.get("name"), category.get("slug"),
        rank.get("name"), rank.get("slug"),
        raw.get("tournamentLevel"), raw.get("rankName"),
    )
    return is_250_plus(match.tour, category_id=source_id, labels=labels)


# Match Winner discovery is deliberately broader than the paid historical
# statistics/ACES scope above. Do not reuse this predicate in CDB gapfills,
# doubles, ESÁ or Viac Es. All newly included fixtures still need valid
# individual identities, pre-start winner odds and standard quality gates.
_UNSAFE_WINNER_LEVEL = re.compile(
    r"\b(?:itf|futures?|utr|juniors?|wheelchair|exhibitions?|next[\s_-]*gen)\b", re.I
)
_CHALLENGER_LABEL = re.compile(r"\bchallengers?\b", re.I)
_WTA125_LABEL = re.compile(r"\bwta[\s_-]*125\b", re.I)
_ITF_GRADE = re.compile(r"(?<![a-z0-9])([mw])[\s_-]?(\d{2,3})(?![a-z0-9])", re.I)
_UNSAFE_ITF_LEVEL = re.compile(r"\b(?:utr|juniors?|wheelchair|exhibitions?|doubles?|mixed|boys?|girls?|next[\s_-]*gen|u1[2468])\b", re.I)


def is_match_winner_offer_scope(tour: str, *, category_id=None, labels=(), event_level=False) -> bool:
    """Include verified ITF M15+/W15+ singles with existing winner competitions.

    Native ITF category IDs open discovery only. Individual events require
    explicit grade evidence, while historical/ACES scope remains 250+.
    """
    if is_250_plus(tour, category_id=category_id, labels=labels):
        return True
    tour = str(tour or "").strip().casefold()
    if tour not in _MAIN_CATEGORY:
        return False
    try:
        category = int(category_id) if category_id not in (None, "") else None
    except (TypeError, ValueError):
        category = None
    label = " ".join(str(item or "") for item in labels).casefold()
    if category in {213, 785}:
        if (tour, category) not in {("atp", 785), ("wta", 213)}:
            return False
        if _UNSAFE_ITF_LEVEL.search(label):
            return False
        if not event_level:
            return True  # Category discovery only; the event gets a strict gate.
        gender = "m" if tour == "atp" else "w"
        grades = _ITF_GRADE.findall(label)
        return bool(grades) and all(
            marker.casefold() == gender and int(amount) >= 15
            for marker, amount in grades
        )
    if _UNSAFE_WINNER_LEVEL.search(label):
        return False
    if tour == "atp" and category in (None, 3, 72) and _CHALLENGER_LABEL.search(label):
        return True
    if tour == "wta" and category in (None, 6, 871) and _WTA125_LABEL.search(label):
        return True
    if category in {72, 871, 213, 785}:
        return False
    if tour == "atp" and "davis cup" in label:
        return True
    if tour == "wta" and ("billie jean king cup" in label or "fed cup" in label):
        return True
    return False
