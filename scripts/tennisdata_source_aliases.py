"""TennisData.app source-native full-name recovery, never a CDB identity crosswalk.

The operator supplied performance snapshots with stable source-local IDs and
unambiguous full names. Expand only exact SHA-pinned season CSV records and
only when BOTH compact source names independently agree with those full names.
The existing CDB linker still requires canonical pair/event/date/winner evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TOUR_LABELS = {
    "atptour": "atp",
    "wtatour": "wta",
    "atpchall": "atp",
    "wtachall": "wta",
}


def _norm(text: str) -> list[str]:
    ascii_text = "".join(
        c for c in unicodedata.normalize("NFKD", str(text))
        if not unicodedata.combining(c)
    ).lower()
    return re.findall(r"[a-z0-9]+", ascii_text)


def compact_matches_full(compact: str, full: str) -> bool:
    """Require exact surname suffix and ordered given-name initials."""
    if _norm(compact) == _norm(full):
        return bool(_norm(full))
    words = str(compact or "").split()
    first_initial = next(
        (i for i, word in enumerate(words) if word.endswith(".")
         and any(ch.isalpha() for ch in word)),
        None,
    )
    if first_initial is None or first_initial < 1:
        return False
    surname = _norm(" ".join(words[:first_initial]))
    full_parts = _norm(full)
    if not surname or len(full_parts) <= len(surname):
        return False
    if full_parts[-len(surname):] != surname:
        return False
    initials = re.findall(r"[a-z]", " ".join(words[first_initial:]).lower())
    given = iter(part[0] for part in full_parts[:-len(surname)])
    return bool(initials) and all(any(letter == ch for ch in given) for letter in initials)


def load_map(path: Path, expected_sha256: str) -> dict:
    if not SHA_RE.fullmatch(str(expected_sha256 or "")):
        raise ValueError("Exact source-name map SHA required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("TennisData source-name map SHA mismatch")
    payload = json.loads(raw)
    if (payload.get("schema") != 1
            or payload.get("mode") != "SOURCE_ONLY_NO_CANONICAL_ID_ASSERTION"):
        raise ValueError("Source-name map is not source-only")
    source_files = payload.get("raw_season_sha256")
    profiles = payload.get("profiles")
    if (not isinstance(source_files, dict)
            or len(source_files) != 12
            or not isinstance(profiles, list)
            or not profiles):
        raise ValueError("Invalid source-name map inventory")
    sha_files: dict[str, str] = {}
    for filename, sha in source_files.items():
        if (not isinstance(filename, str) or
                not re.fullmatch(r"20(?:2[1-6])-(?:atp|wta)-season\(1\)\.csv", filename)
                or not isinstance(sha, str) or not SHA_RE.fullmatch(sha)
                or sha in sha_files):
            raise ValueError("Invalid or duplicate exact CSV source SHA")
        sha_files[sha] = filename
    by_id: dict[tuple[str, str], str] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("Invalid source player profile")
        tour = profile.get("tour")
        local_id = profile.get("local_id")
        name = profile.get("full_name")
        if (tour not in ("atp", "wta")
                or not isinstance(local_id, str)
                or not re.fullmatch(r"[0-9]{1,16}", local_id)
                or not isinstance(name, str)
                or not 3 <= len(name) <= 120
                or not _norm(name)):
            raise ValueError("Invalid source player identity")
        key = (tour, local_id)
        if key in by_id:
            raise ValueError("Conflicting or duplicate source player ID")
        by_id[key] = name
    return {"sha_files": sha_files, "profiles": by_id, "sha256": expected_sha256}


def expand_pair(row: dict, source_sha256: str, source_map: dict) -> tuple[dict, str]:
    """Recover only the same provider's two names; never infer canonical IDs."""
    if source_sha256 not in source_map["sha_files"]:
        return row, "source_sha_not_in_pinned_batch"
    tour_label = re.sub(r"[^a-z0-9]", "", str(row.get("tour_type_human") or "").lower())
    tour = TOUR_LABELS.get(tour_label)
    if not tour:
        return row, "unrecognized_tour"
    home_id, away_id = str(row.get("home_id") or ""), str(row.get("away_id") or "")
    if not home_id or not away_id or home_id == away_id:
        return row, "missing_or_equal_player_ids"
    names = source_map["profiles"]
    home = names.get((tour, home_id))
    away = names.get((tour, away_id))
    if not home or not away or _norm(home) == _norm(away):
        return row, "not_both_uniquely_named"
    if not (compact_matches_full(str(row.get("home_name") or ""), home)
            and compact_matches_full(str(row.get("away_name") or ""), away)):
        return row, "compact_full_name_disagreement"
    enriched = dict(row)
    enriched["home_name"] = home
    enriched["away_name"] = away
    return enriched, "two_source_names_verified"

# Curated from the owner's independently compared, SHA-identical TennisData
# and TML+ season sources (4,336 row-level matches across 2021-2026).
# Each corroboration required the same winner/loser, ordered initials, exact
# round + surface, a bounded forward tournament window, 4 equal ace/DF counts,
# both consistent service percentages, and at least one matching BP rate.
# These are source-local display-name translations, NEVER canonical identity.
# The strict CDB linker STILL requires exact canonical event, date, winner,
# unique player pair and round/surface. Avoid ambiguous Challenger numbering.
VERIFIED_EVENT_ALIASES = {
    ("atp", "French Open ATP"): "Roland Garros",
    ("wta", "French Open WTA"): "Roland Garros",
    ("atp", "Miami ATP"): "Miami Masters",
    ("atp", "Indian Wells ATP"): "Indian Wells Masters",
    ("atp", "Rome ATP"): "Rome Masters",
    ("atp", "Madrid ATP"): "Madrid Masters",
    ("atp", "Cincinnati ATP"): "Cincinnati Masters",
    ("atp", "Paris ATP (indoor)"): "Paris Masters",
    ("atp", "Monte Carlo ATP"): "Monte Carlo Masters",
    ("atp", "Shanghai ATP"): "Shanghai Masters",
    ("atp", "Toronto ATP"): "Canada Masters",
    ("atp", "Montreal ATP"): "Canada Masters",
}


def expand_verified_event(row: dict, source_sha256: str, source_map: dict) -> tuple[dict, str]:
    """Optional exact-source event-name expansion, never an identity shortcut."""
    if source_sha256 not in source_map["sha_files"]:
        return row, "source_sha_not_in_pinned_batch"
    tour_label = re.sub(r"[^a-z0-9]", "", str(row.get("tour_type_human") or "").lower())
    # Explicitly exclude Challenger events; their numbered editions are
    # not safely interchangeable even if their city names agree.
    if tour_label not in ("atptour", "wtatour"):
        return row, "not_main_tour"
    tour = TOUR_LABELS[tour_label]
    tournament = row.get("tournament")
    alias = VERIFIED_EVENT_ALIASES.get((tour, tournament))
    if alias is None:
        return row, "not_whitelisted"
    expanded = dict(row)
    expanded["tournament"] = alias
    return expanded, "exact_whitelist_hit"
