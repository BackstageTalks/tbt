from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from ..services.countries import normalize_country_code


def normalize_player_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def initial_surname_key(value: object) -> str:
    parts = normalize_player_name(value).split()
    if len(parts) < 2:
        return ""
    return f"{parts[0][0]} {parts[-1]}"


def normalize_birth_date(value: object) -> str:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    if len(text) == 8:
        return text
    return ""


def _profile_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows = payload.get("players")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(rows, dict):
        return [
            dict(row, id=row.get("id", key))
            for key, row in rows.items()
            if isinstance(row, dict)
        ]
    return []


def load_profiles(path: str | Path | None) -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    by_tour_id: dict[tuple[str, str], dict] = {}
    by_id: dict[str, dict] = {}
    if not path or not Path(path).is_file():
        return by_tour_id, by_id
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    for row in _profile_rows(payload):
        pid = str(
            row.get("id")
            or row.get("player_id")
            or row.get("api_team_id")
            or row.get("team_id")
            or ""
        ).strip()
        if not pid:
            continue
        tour = str(row.get("tour") or "").strip().lower()
        by_id[pid] = row
        if tour:
            by_tour_id[(tour, pid)] = row
    return by_tour_id, by_id


def _payload_country(payload: dict, side: int) -> str:
    if not isinstance(payload, dict):
        return ""
    keys = (
        ("homeTeam", "home_team", "player1", "participant1", "player_1")
        if side == 1
        else ("awayTeam", "away_team", "player2", "participant2", "player_2")
    )
    value = next((payload.get(key) for key in keys if isinstance(payload.get(key), dict)), {})
    candidates = []
    if isinstance(value, dict):
        candidates += [
            value.get("country_code"),
            value.get("countryCode"),
            value.get("countryAlpha2"),
            value.get("countryAlpha3"),
        ]
        country = value.get("country")
        if isinstance(country, dict):
            candidates += [
                country.get("alpha2"),
                country.get("alpha3"),
                country.get("code"),
            ]
        else:
            candidates.append(country)
    for candidate in candidates:
        code = normalize_country_code(candidate)
        if code:
            return code
    return ""


def _profile_country(profile: dict[str, Any]) -> str:
    candidates = [
        profile.get("country_code"),
        profile.get("country_code2"),
        profile.get("country_code3"),
        profile.get("countryAlpha2"),
        profile.get("countryAlpha3"),
    ]
    country = profile.get("country")
    if isinstance(country, dict):
        candidates += [country.get("alpha2"), country.get("alpha3"), country.get("code")]
    else:
        candidates.append(country)
    for candidate in candidates:
        code = normalize_country_code(candidate)
        if code:
            return code
    return ""


def build_canonical_players(
    matches: Iterable,
    *,
    tour: str,
    profile_by_tour_id: dict[tuple[str, str], dict] | None = None,
    profile_by_id: dict[str, dict] | None = None,
) -> list[dict[str, Any]]:
    profile_by_tour_id = profile_by_tour_id or {}
    profile_by_id = profile_by_id or {}
    target = str(tour).lower()
    rows: dict[str, dict[str, Any]] = {}
    countries: dict[str, Counter] = defaultdict(Counter)

    for match in matches:
        if str(getattr(match, "tour", "") or "").lower() != target:
            continue
        for side in (1, 2):
            pid = str(getattr(match, f"player{side}_id") or "").strip()
            if not pid:
                continue
            name = str(getattr(match, f"player{side}_name") or "").strip()
            row = rows.setdefault(
                pid,
                {
                    "canonical_player_id": pid,
                    "tour": target,
                    "name": name,
                    "aliases": set(),
                    "country_code": "",
                    "birth_date": "",
                    "hand": "",
                    "matches_seen": 0,
                },
            )
            row["matches_seen"] += 1
            if name:
                row["aliases"].add(name)
                row["name"] = name
            country = _payload_country(getattr(match, "provider_payload", {}) or {}, side)
            if country:
                countries[pid][country] += 1

    for pid, row in rows.items():
        if countries[pid]:
            row["country_code"] = countries[pid].most_common(1)[0][0]
        profile = profile_by_tour_id.get((target, pid)) or profile_by_id.get(pid) or {}
        if profile:
            for key in ("name", "display_name", "canonical_name", "player_name"):
                if profile.get(key):
                    row["aliases"].add(str(profile[key]).strip())
            for alias in profile.get("aliases") or []:
                if alias:
                    row["aliases"].add(str(alias).strip())
            row["birth_date"] = normalize_birth_date(
                profile.get("birth_date")
                or profile.get("date_of_birth")
                or profile.get("dateOfBirth")
            )
            row["hand"] = str(profile.get("hand") or profile.get("plays") or "").strip().upper()
            pcountry = _profile_country(profile)
            if pcountry:
                row["country_code"] = pcountry
        row["aliases"] = sorted(x for x in row["aliases"] if x)
    return sorted(rows.values(), key=lambda item: item["canonical_player_id"])


def load_sackmann_players(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            pid = str(raw.get("player_id") or "").strip()
            if not pid:
                continue
            first = str(raw.get("name_first") or raw.get("first_name") or "").strip()
            last = str(raw.get("name_last") or raw.get("last_name") or "").strip()
            name = " ".join(part for part in (first, last) if part).strip()
            if not name:
                continue
            rows.append(
                {
                    "sackmann_player_id": pid,
                    "name": name,
                    "normalized_name": normalize_player_name(name),
                    "short_key": initial_surname_key(name),
                    "birth_date": normalize_birth_date(
                        raw.get("birth_date") or raw.get("dob")
                    ),
                    "country_code": normalize_country_code(
                        raw.get("country_code") or raw.get("country")
                    )
                    or "",
                    "hand": str(raw.get("hand") or "").strip().upper(),
                }
            )
    return rows


def build_crosswalk(
    canonical_players: Iterable[dict[str, Any]],
    sackmann_players: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canonical = list(canonical_players)
    sackmann = list(sackmann_players)
    by_name: dict[str, list[dict]] = defaultdict(list)
    by_short: dict[str, list[dict]] = defaultdict(list)
    for row in sackmann:
        by_name[row["normalized_name"]].append(row)
        if row["short_key"]:
            by_short[row["short_key"]].append(row)

    resolved = []
    unresolved = []
    evidence_counts = Counter()

    for player in canonical:
        aliases = sorted(
            {
                normalize_player_name(alias)
                for alias in ([player.get("name", "")] + list(player.get("aliases") or []))
                if normalize_player_name(alias)
            }
        )
        birth_date = normalize_birth_date(player.get("birth_date"))
        country = normalize_country_code(player.get("country_code")) or ""

        exact_candidates: dict[str, dict] = {}
        matched_aliases = []
        for alias in aliases:
            matches = by_name.get(alias, [])
            if matches:
                matched_aliases.append(alias)
            for item in matches:
                exact_candidates[item["sackmann_player_id"]] = item

        chosen = None
        evidence = ""
        if len(exact_candidates) == 1:
            chosen = next(iter(exact_candidates.values()))
            evidence = "unique_exact_alias"
        elif exact_candidates:
            candidates = list(exact_candidates.values())
            if birth_date:
                dob = [item for item in candidates if item["birth_date"] == birth_date]
                if len(dob) == 1:
                    chosen = dob[0]
                    evidence = "exact_alias_plus_dob"
            if chosen is None and country:
                same_country = [item for item in candidates if item["country_code"] == country]
                if len(same_country) == 1:
                    chosen = same_country[0]
                    evidence = "exact_alias_plus_country"

        if chosen is None and birth_date:
            short_candidates: dict[str, dict] = {}
            for alias in aliases:
                key = initial_surname_key(alias)
                if not key:
                    continue
                for item in by_short.get(key, []):
                    if item["birth_date"] == birth_date:
                        short_candidates[item["sackmann_player_id"]] = item
            if len(short_candidates) == 1:
                chosen = next(iter(short_candidates.values()))
                evidence = "initial_surname_plus_dob"

        if chosen is None:
            unresolved.append(
                {
                    "canonical_player_id": player["canonical_player_id"],
                    "name": player.get("name", ""),
                    "aliases": player.get("aliases", []),
                    "birth_date": birth_date,
                    "country_code": country,
                    "exact_candidate_count": len(exact_candidates),
                }
            )
            continue

        evidence_counts[evidence] += 1
        resolved.append(
            {
                "canonical_player_id": player["canonical_player_id"],
                "tour": player.get("tour"),
                "canonical_name": player.get("name", ""),
                "sackmann_player_id": chosen["sackmann_player_id"],
                "sackmann_name": chosen["name"],
                "evidence": evidence,
                "birth_date_match": bool(
                    birth_date and chosen.get("birth_date") == birth_date
                ),
                "country_match": bool(
                    country and chosen.get("country_code") == country
                ),
                "matched_aliases": matched_aliases,
            }
        )

    canonical_count = len(canonical)
    report = {
        "schema": 1,
        "canonical_players": canonical_count,
        "sackmann_players": len(sackmann),
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "coverage": (len(resolved) / canonical_count) if canonical_count else 0.0,
        "evidence_counts": dict(evidence_counts),
        "unresolved_players": unresolved[:1000],
        "policy": (
            "fail_closed: unique exact alias; duplicate exact alias disambiguated "
            "by exact DOB/country; initial+surname requires exact DOB"
        ),
    }
    return resolved, report


def crosswalk_mapping(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {
        str(row["canonical_player_id"]): str(row["sackmann_player_id"])
        for row in rows
        if row.get("canonical_player_id") and row.get("sackmann_player_id")
    }


def load_crosswalk(path: str | Path | None) -> dict[str, str]:
    if not path or not Path(path).is_file():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("players") if isinstance(payload, dict) else payload
    return crosswalk_mapping(rows or [])
