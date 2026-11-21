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
    r"exhibitions?|next[\s_-]*gen)\b|\bwta[\s_-]*125\b",
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
