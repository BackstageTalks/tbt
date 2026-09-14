"""Build production tournament and venue masters from canonical history.

The builder is intentionally read-only. It only uses point-in-time/canonical history
that is already present in tbt-data-v1; it performs no network calls.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.services.countries import normalize_country_code


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def _country_code(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("alpha2", "alpha3", "code", "iso2", "iso3"):
            code = normalize_country_code(value.get(key))
            if code:
                return code
        return ""
    return normalize_country_code(value)


def _payload_location(payload: Any) -> dict[str, str]:
    raw = _dict(payload)
    tournament = _dict(raw.get("tournament"))
    unique = _dict(tournament.get("uniqueTournament"))
    venue = _dict(raw.get("venue"))

    country = (
        _country_code(venue.get("country"))
        or _country_code(tournament.get("country"))
        or _country_code(unique.get("country"))
        or _country_code(raw.get("country"))
        or normalize_country_code(raw.get("countryName"))
    )
    city = _text(
        venue.get("city")
        or tournament.get("city")
        or unique.get("city")
        or raw.get("venueCity")
        or raw.get("city")
    )
    venue_name = _text(venue.get("name"))
    venue_id = _text(venue.get("id"))
    return {
        "country_code": country,
        "city": city,
        "venue_name": venue_name,
        "venue_id": venue_id,
    }


def _environment(payload: Any) -> dict[str, Any]:
    return _dict(_dict(payload).get("_tbt_environment"))


def _resolved_venue(payload: Any) -> dict[str, Any]:
    env = _environment(payload)
    venue = _dict(env.get("venue"))
    if not venue or env.get("venue_resolved") is not True:
        return {}
    return venue


def _tournament_key(match) -> str:
    tour = _text(match.tour).lower() or "unknown"
    tournament_id = _text(match.tournament_id)
    if tournament_id:
        return f"{tour}:id:{tournament_id}"
    return f"{tour}:name:{_slug(_text(match.tournament))}"


def _venue_key(match, payload_location: dict[str, str], resolved: dict[str, Any]) -> str:
    tour = _text(match.tour).lower() or "unknown"
    provider_venue_id = payload_location.get("venue_id") or ""
    if provider_venue_id:
        return f"provider:{provider_venue_id}"
    lat = resolved.get("latitude")
    lon = resolved.get("longitude")
    if lat not in (None, "") and lon not in (None, ""):
        try:
            return f"geo:{float(lat):.4f}:{float(lon):.4f}"
        except (TypeError, ValueError):
            pass
    tid = _text(match.tournament_id)
    if tid:
        return f"{tour}:tournament:{tid}"
    city = payload_location.get("city") or _text(resolved.get("name")) or _text(match.tournament)
    country = payload_location.get("country_code") or normalize_country_code(resolved.get("country"))
    return f"{tour}:location:{_slug(city)}:{country or 'xx'}"


def _mode(counter: Counter) -> Any:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build(matches) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    tournaments: dict[str, dict[str, Any]] = {}
    venues: dict[str, dict[str, Any]] = {}
    tournament_names: dict[str, Counter] = defaultdict(Counter)
    tournament_levels: dict[str, Counter] = defaultdict(Counter)
    tournament_surfaces: dict[str, Counter] = defaultdict(Counter)
    tournament_indoor: dict[str, Counter] = defaultdict(Counter)
    tournament_cities: dict[str, Counter] = defaultdict(Counter)
    tournament_countries: dict[str, Counter] = defaultdict(Counter)
    tournament_venues: dict[str, set[str]] = defaultdict(set)
    venue_names: dict[str, Counter] = defaultdict(Counter)
    venue_cities: dict[str, Counter] = defaultdict(Counter)
    venue_countries: dict[str, Counter] = defaultdict(Counter)
    venue_timezones: dict[str, Counter] = defaultdict(Counter)

    for match in matches:
        tkey = _tournament_key(match)
        ts = match.scheduled_at.isoformat()
        loc = _payload_location(match.provider_payload)
        resolved = _resolved_venue(match.provider_payload)
        vkey = _venue_key(match, loc, resolved)
        tournament_venues[tkey].add(vkey)

        row = tournaments.setdefault(tkey, {
            "tournament_key": tkey,
            "tournament_id": _text(match.tournament_id),
            "tour": _text(match.tour).lower(),
            "name": _text(match.tournament),
            "level": _text(match.tournament_level),
            "surface": _text(match.surface).lower(),
            "indoor": match.indoor,
            "city": loc.get("city", ""),
            "country_code": loc.get("country_code", ""),
            "first_seen": ts,
            "last_seen": ts,
            "matches_seen": 0,
            "venue_resolved_matches": 0,
            "environment_present_matches": 0,
            "venue_keys": [],
        })
        row["matches_seen"] += 1
        row["first_seen"] = min(row["first_seen"], ts)
        row["last_seen"] = max(row["last_seen"], ts)
        if _environment(match.provider_payload):
            row["environment_present_matches"] += 1
        if resolved:
            row["venue_resolved_matches"] += 1

        if match.tournament:
            tournament_names[tkey][_text(match.tournament)] += 1
        if match.tournament_level:
            tournament_levels[tkey][_text(match.tournament_level)] += 1
        if match.surface and _text(match.surface).lower() != "unknown":
            tournament_surfaces[tkey][_text(match.surface).lower()] += 1
        if match.indoor is not None:
            tournament_indoor[tkey][bool(match.indoor)] += 1
        if loc.get("city"):
            tournament_cities[tkey][loc["city"]] += 1
        if loc.get("country_code"):
            tournament_countries[tkey][loc["country_code"]] += 1

        vrow = venues.setdefault(vkey, {
            "venue_key": vkey,
            "provider_venue_id": loc.get("venue_id", ""),
            "name": loc.get("venue_name", "") or _text(resolved.get("name")),
            "city": loc.get("city", ""),
            "country_code": loc.get("country_code", "") or normalize_country_code(resolved.get("country")),
            "latitude": None,
            "longitude": None,
            "elevation_m": None,
            "timezone": "",
            "first_seen": ts,
            "last_seen": ts,
            "matches_seen": 0,
            "resolved_matches": 0,
            "tournament_keys": set(),
        })
        vrow["matches_seen"] += 1
        vrow["first_seen"] = min(vrow["first_seen"], ts)
        vrow["last_seen"] = max(vrow["last_seen"], ts)
        vrow["tournament_keys"].add(tkey)
        if resolved:
            vrow["resolved_matches"] += 1
            for field, source in (("latitude", "latitude"), ("longitude", "longitude"), ("elevation_m", "elevation_m")):
                if resolved.get(source) not in (None, ""):
                    try:
                        vrow[field] = float(resolved[source])
                    except (TypeError, ValueError):
                        pass
            if resolved.get("timezone"):
                venue_timezones[vkey][_text(resolved.get("timezone"))] += 1
            if resolved.get("name"):
                venue_names[vkey][_text(resolved.get("name"))] += 1
            if resolved.get("country"):
                code = normalize_country_code(resolved.get("country"))
                if code:
                    venue_countries[vkey][code] += 1
        if loc.get("venue_name"):
            venue_names[vkey][loc["venue_name"]] += 1
        if loc.get("city"):
            venue_cities[vkey][loc["city"]] += 1
        if loc.get("country_code"):
            venue_countries[vkey][loc["country_code"]] += 1

    tournament_rows: list[dict[str, Any]] = []
    for key, row in tournaments.items():
        row["name"] = _mode(tournament_names[key]) or row["name"]
        row["level"] = _mode(tournament_levels[key]) or row["level"]
        row["surface"] = _mode(tournament_surfaces[key]) or row["surface"] or "unknown"
        indoor_mode = _mode(tournament_indoor[key])
        row["indoor"] = indoor_mode if indoor_mode is not None else row["indoor"]
        row["city"] = _mode(tournament_cities[key]) or row["city"]
        row["country_code"] = _mode(tournament_countries[key]) or row["country_code"]
        row["venue_keys"] = sorted(tournament_venues[key])
        row["name_aliases"] = sorted(name for name in tournament_names[key] if name and name != row["name"])
        row["level_values"] = sorted(str(v) for v in tournament_levels[key] if str(v))
        row["surface_values"] = sorted(str(v) for v in tournament_surfaces[key] if str(v))
        row["indoor_values"] = sorted(bool(v) for v in tournament_indoor[key])
        row["country_values"] = sorted(str(v) for v in tournament_countries[key] if str(v))
        row["city_values"] = sorted(str(v) for v in tournament_cities[key] if str(v))
        row["venue_resolved_rate"] = round(row["venue_resolved_matches"] / max(1, row["matches_seen"]), 6)
        row["environment_present_rate"] = round(row["environment_present_matches"] / max(1, row["matches_seen"]), 6)
        row["identity_signature"] = "|".join([
            row["tour"] or "unknown", _slug(row["name"]), row["country_code"] or "xx", _slug(row["city"] or "unknown")
        ])
        tournament_rows.append(row)

    venue_rows: list[dict[str, Any]] = []
    for key, row in venues.items():
        row["name"] = _mode(venue_names[key]) or row["name"]
        row["city"] = _mode(venue_cities[key]) or row["city"]
        row["country_code"] = _mode(venue_countries[key]) or row["country_code"]
        row["timezone"] = _mode(venue_timezones[key]) or row["timezone"]
        row["name_values"] = sorted(str(v) for v in venue_names[key] if str(v))
        row["city_values"] = sorted(str(v) for v in venue_cities[key] if str(v))
        row["country_values"] = sorted(str(v) for v in venue_countries[key] if str(v))
        row["timezone_values"] = sorted(str(v) for v in venue_timezones[key] if str(v))
        row["tournament_keys"] = sorted(row["tournament_keys"])
        row["resolved_rate"] = round(row["resolved_matches"] / max(1, row["matches_seen"]), 6)
        venue_rows.append(row)

    tournament_rows.sort(key=lambda r: (r["tour"], r["name"].casefold(), r["tournament_key"]))
    venue_rows.sort(key=lambda r: (r["country_code"], r["city"].casefold(), r["name"].casefold(), r["venue_key"]))

    total_t = len(tournament_rows)
    total_v = len(venue_rows)
    signature_groups: dict[str, list[str]] = defaultdict(list)
    for row in tournament_rows:
        # Only diagnose potential duplicates when the name is meaningful and at
        # least one geographic discriminator is known. Never auto-merge here.
        if row["name"] and (row["country_code"] or row["city"]):
            signature_groups[row["identity_signature"]].append(row["tournament_key"])
    potential_duplicate_tournaments = {
        sig: sorted(keys) for sig, keys in signature_groups.items() if len(set(keys)) > 1
    }
    tournament_conflicts = {
        row["tournament_key"]: {
            "levels": row["level_values"], "surfaces": row["surface_values"],
            "indoor": row["indoor_values"], "countries": row["country_values"],
            "cities": row["city_values"],
        }
        for row in tournament_rows
        if any(len(row[field]) > 1 for field in ("level_values", "surface_values", "indoor_values", "country_values", "city_values"))
    }
    venue_conflicts = {
        row["venue_key"]: {
            "names": row["name_values"], "cities": row["city_values"],
            "countries": row["country_values"], "timezones": row["timezone_values"],
        }
        for row in venue_rows
        if any(len(row[field]) > 1 for field in ("city_values", "country_values", "timezone_values"))
    }

    by_tour = {}
    for tour in sorted({row["tour"] for row in tournament_rows}):
        subset = [row for row in tournament_rows if row["tour"] == tour]
        by_tour[tour] = {
            "tournaments": len(subset),
            "country_coverage": round(sum(bool(r["country_code"]) for r in subset) / max(1, len(subset)), 6),
            "city_coverage": round(sum(bool(r["city"]) for r in subset) / max(1, len(subset)), 6),
            "surface_coverage": round(sum(r["surface"] not in ("", "unknown") for r in subset) / max(1, len(subset)), 6),
            "indoor_coverage": round(sum(r["indoor"] is not None for r in subset) / max(1, len(subset)), 6),
            "any_resolved_venue_coverage": round(sum(r["venue_resolved_matches"] > 0 for r in subset) / max(1, len(subset)), 6),
        }

    report = {
        "schema": 2,
        "matches": len(matches),
        "tournaments": total_t,
        "venues": total_v,
        "tournament_coverage": {
            "country": round(sum(bool(r["country_code"]) for r in tournament_rows) / max(1, total_t), 6),
            "city": round(sum(bool(r["city"]) for r in tournament_rows) / max(1, total_t), 6),
            "surface": round(sum(r["surface"] not in ("", "unknown") for r in tournament_rows) / max(1, total_t), 6),
            "indoor": round(sum(r["indoor"] is not None for r in tournament_rows) / max(1, total_t), 6),
            "any_resolved_venue": round(sum(r["venue_resolved_matches"] > 0 for r in tournament_rows) / max(1, total_t), 6),
        },
        "venue_coverage": {
            "country": round(sum(bool(r["country_code"]) for r in venue_rows) / max(1, total_v), 6),
            "city": round(sum(bool(r["city"]) for r in venue_rows) / max(1, total_v), 6),
            "coordinates": round(sum(r["latitude"] is not None and r["longitude"] is not None for r in venue_rows) / max(1, total_v), 6),
            "elevation": round(sum(r["elevation_m"] is not None for r in venue_rows) / max(1, total_v), 6),
            "timezone": round(sum(bool(r["timezone"]) for r in venue_rows) / max(1, total_v), 6),
        },
        "by_tour": by_tour,
        "identity_diagnostics": {
            "potential_duplicate_signature_groups": len(potential_duplicate_tournaments),
            "potential_duplicate_tournaments": potential_duplicate_tournaments,
            "tournament_conflict_groups": len(tournament_conflicts),
            "tournament_conflicts": tournament_conflicts,
            "venue_conflict_groups": len(venue_conflicts),
            "venue_conflicts": venue_conflicts,
            "policy": "report_only_never_auto_merge",
        },
        "missing": {
            "tournaments_without_country": [r["tournament_key"] for r in tournament_rows if not r["country_code"]],
            "tournaments_without_city": [r["tournament_key"] for r in tournament_rows if not r["city"]],
            "venues_without_coordinates": [r["venue_key"] for r in venue_rows if r["latitude"] is None or r["longitude"] is None],
            "venues_without_elevation": [r["venue_key"] for r in venue_rows if r["elevation_m"] is None],
            "venues_without_timezone": [r["venue_key"] for r in venue_rows if not r["timezone"]],
        },
    }
    return tournament_rows, venue_rows, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default=".cache/tbt/history")
    parser.add_argument("--tournaments-out", default=".cache/tbt/production/tournament_master.json")
    parser.add_argument("--tournaments-csv", default=".cache/tbt/production/tournament_master.csv")
    parser.add_argument("--venues-out", default=".cache/tbt/production/venue_master.json")
    parser.add_argument("--venues-csv", default=".cache/tbt/production/venue_master.csv")
    parser.add_argument("--report", default=".cache/tbt/production/tournament_venue_report.json")
    args = parser.parse_args()

    matches = load_partitions(Path(args.history_dir))
    tournament_rows, venue_rows, report = build(matches)

    t_out = Path(args.tournaments_out); t_out.parent.mkdir(parents=True, exist_ok=True)
    t_out.write_text(json.dumps({"schema": 2, "tournaments": tournament_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    v_out = Path(args.venues_out); v_out.parent.mkdir(parents=True, exist_ok=True)
    v_out.write_text(json.dumps({"schema": 2, "venues": venue_rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    _write_csv(Path(args.tournaments_csv), tournament_rows, [
        "tournament_key", "tournament_id", "tour", "name", "level", "surface", "indoor",
        "city", "country_code", "first_seen", "last_seen", "matches_seen",
        "venue_resolved_matches", "venue_resolved_rate", "environment_present_rate", "venue_keys",
    ])
    _write_csv(Path(args.venues_csv), venue_rows, [
        "venue_key", "provider_venue_id", "name", "city", "country_code", "latitude", "longitude",
        "elevation_m", "timezone", "first_seen", "last_seen", "matches_seen", "resolved_matches",
        "resolved_rate", "tournament_keys",
    ])

    report.update({
        "tournament_json": str(t_out),
        "venue_json": str(v_out),
    })
    report_path = Path(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
