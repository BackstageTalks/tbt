"""Build a production player master from canonical history and optional profiles.

The master is an identity/presentation artifact, not a training feature source.  It
aggregates country evidence across *all* canonical rows so a missing country on the
latest event cannot erase a country observed earlier.  Optional player profiles are
preferred when present and their provenance is recorded explicitly.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.services.countries import normalize_country_code


def _country_from_payload(payload: dict, player1: bool) -> str:
    if not isinstance(payload, dict):
        return ""
    keys = ("homeTeam", "home_team", "player1", "participant1", "player_1") if player1 else ("awayTeam", "away_team", "player2", "participant2", "player_2")
    side = next((payload.get(k) for k in keys if isinstance(payload.get(k), dict)), {})
    candidates: list[Any] = []
    if isinstance(side, dict):
        candidates.extend([
            side.get("country_code"), side.get("countryCode"),
            side.get("countryAlpha2"), side.get("countryAlpha3"),
            side.get("country_code2"), side.get("country_code3"),
        ])
        country = side.get("country")
        if isinstance(country, dict):
            candidates.extend([
                country.get("alpha2"), country.get("alpha3"), country.get("code"),
                country.get("iso2"), country.get("iso3"),
            ])
        else:
            candidates.append(country)
    for value in candidates:
        code = normalize_country_code(value)
        if code:
            return code
    return ""


def _profile_country(profile: dict[str, Any]) -> str:
    if not isinstance(profile, dict):
        return ""
    candidates = [
        profile.get("country_code"), profile.get("country_code2"),
        profile.get("country_code3"), profile.get("countryAlpha2"),
        profile.get("countryAlpha3"),
    ]
    country = profile.get("country")
    if isinstance(country, dict):
        candidates += [country.get("alpha2"), country.get("alpha3"), country.get("code")]
    else:
        candidates.append(country)
    for value in candidates:
        code = normalize_country_code(value)
        if code:
            return code
    return ""


def _load_profiles(path: str) -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    by_tour_id: dict[tuple[str, str], dict] = {}
    by_id: dict[str, dict] = {}
    if not path or not Path(path).is_file():
        return by_tour_id, by_id
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("players") if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = [dict(v, id=v.get("id", k)) for k, v in rows.items() if isinstance(v, dict)]
    if not isinstance(rows, list):
        return by_tour_id, by_id
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or row.get("player_id") or "").strip()
        if not pid:
            continue
        tour = str(row.get("tour") or "").strip().lower()
        by_id[pid] = row
        if tour:
            by_tour_id[(tour, pid)] = row
    return by_tour_id, by_id


def _coverage(rows: list[dict], field: str, predicate=None) -> float:
    if not rows:
        return 0.0
    if predicate is None:
        predicate = lambda value: value not in (None, "")
    return round(sum(bool(predicate(row.get(field))) for row in rows) / len(rows), 6)


def build(matches, profile_by_tour_id=None, profile_by_id=None) -> tuple[list[dict], dict]:
    profile_by_tour_id = profile_by_tour_id or {}
    profile_by_id = profile_by_id or {}
    master: dict[tuple[str, str], dict] = {}
    aliases: dict[tuple[str, str], set[str]] = defaultdict(set)
    country_votes: dict[tuple[str, str], Counter] = defaultdict(Counter)

    for match in matches:
        for idx in (1, 2):
            pid = str(getattr(match, f"player{idx}_id") or "").strip()
            if not pid:
                continue
            tour = str(match.tour or "").strip().lower() or "unknown"
            key = (tour, pid)
            name = str(getattr(match, f"player{idx}_name") or "").strip()
            rank = getattr(match, f"player{idx}_rank")
            ts = match.scheduled_at.isoformat()
            if name:
                aliases[key].add(name)
            code = _country_from_payload(match.provider_payload, player1=idx == 1)
            if code:
                country_votes[key][code] += 1

            row = master.setdefault(key, {
                "player_id": pid, "tour": tour, "name": name,
                "country_code": "", "country_source": "missing",
                "latest_rank": None, "rank_source": "missing",
                "profile_enriched": False,
                "first_seen": ts, "last_seen": ts,
                "matches_seen": 0, "aliases": [],
            })
            row["matches_seen"] += 1
            if ts < row["first_seen"]:
                row["first_seen"] = ts
            if ts >= row["last_seen"]:
                row["last_seen"] = ts
                if name:
                    row["name"] = name
                if rank not in (None, ""):
                    try:
                        row["latest_rank"] = int(rank)
                        row["rank_source"] = "history_latest_observed"
                    except (TypeError, ValueError):
                        pass

    for key, row in master.items():
        tour, pid = key
        if country_votes[key]:
            row["country_code"] = country_votes[key].most_common(1)[0][0]
            row["country_source"] = "history_consensus"

        profile = profile_by_tour_id.get(key) or profile_by_id.get(pid) or {}
        if profile:
            row["profile_enriched"] = True
            code = _profile_country(profile)
            if code:
                row["country_code"] = code
                row["country_source"] = "profile"
            rank = profile.get("rank", profile.get("ranking"))
            if rank not in (None, ""):
                try:
                    row["latest_rank"] = int(rank)
                    row["rank_source"] = "profile"
                except (TypeError, ValueError):
                    pass
            for source, target in (
                ("hand", "hand"), ("birth_date", "birth_date"),
                ("height_cm", "height_cm"), ("photo_file", "photo_file"),
                ("photo_url", "photo_url"), ("best_rank", "best_rank"),
            ):
                if profile.get(source) not in (None, ""):
                    row[target] = profile[source]
            if profile.get("name"):
                row["name"] = str(profile["name"]).strip()

        row["aliases"] = sorted(x for x in aliases[key] if x and x != row["name"])
        row["alias_count"] = len(row["aliases"])
        row["identity_key"] = f"{tour}:{pid}"

    rows = sorted(master.values(), key=lambda r: (r["tour"], r["name"].casefold(), r["player_id"]))

    duplicate_names: dict[str, list[str]] = {}
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    ids_across_tours: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_name[(row["tour"], row["name"].casefold())].append(row["player_id"])
        ids_across_tours[row["player_id"]].add(row["tour"])
    for (tour, name), ids in by_name.items():
        if name and len(set(ids)) > 1:
            duplicate_names[f"{tour}:{name}"] = sorted(set(ids))

    by_tour = {}
    for tour in sorted({row["tour"] for row in rows}):
        subset = [row for row in rows if row["tour"] == tour]
        by_tour[tour] = {
            "players": len(subset),
            "country_coverage": _coverage(subset, "country_code"),
            "latest_rank_coverage": _coverage(subset, "latest_rank"),
            "profile_coverage": _coverage(subset, "profile_enriched", bool),
            "photo_coverage": _coverage(subset, "photo_file", lambda v: bool(v)) if any("photo_file" in r for r in subset) else 0.0,
        }

    report = {
        "schema": 2,
        "players": len(rows),
        "country_coverage": _coverage(rows, "country_code"),
        "latest_rank_coverage": _coverage(rows, "latest_rank"),
        "profile_coverage": _coverage(rows, "profile_enriched", bool),
        "missing_country": sum(not row.get("country_code") for row in rows),
        "missing_latest_rank": sum(row.get("latest_rank") in (None, "") for row in rows),
        "country_source_counts": dict(Counter(row.get("country_source") for row in rows)),
        "rank_source_counts": dict(Counter(row.get("rank_source") for row in rows)),
        "by_tour": by_tour,
        "duplicate_name_groups": len(duplicate_names),
        "duplicate_names": duplicate_names,
        "player_ids_seen_on_multiple_tours": {
            pid: sorted(tours) for pid, tours in ids_across_tours.items() if len(tours) > 1
        },
        "players_missing_country": [
            {"tour": r["tour"], "player_id": r["player_id"], "name": r["name"]}
            for r in rows if not r.get("country_code")
        ],
    }
    return rows, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default=".cache/tbt/history")
    parser.add_argument("--profiles", default="")
    parser.add_argument("--out", default=".cache/tbt/player_master.json")
    parser.add_argument("--csv", dest="csv_out", default=".cache/tbt/player_master.csv")
    parser.add_argument("--report", default=".cache/tbt/player_master_report.json")
    args = parser.parse_args()

    matches, identity_safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    profile_by_tour_id, profile_by_id = _load_profiles(args.profiles)
    rows, report = build(matches, profile_by_tour_id, profile_by_id)
    report["identity_safety"] = identity_safety

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": 2, "players": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_out = Path(args.csv_out); csv_out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "identity_key", "player_id", "tour", "name", "country_code", "country_source",
        "latest_rank", "rank_source", "best_rank", "hand", "birth_date", "height_cm",
        "photo_file", "photo_url", "profile_enriched", "first_seen", "last_seen",
        "matches_seen", "alias_count", "aliases",
    ]
    with csv_out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = dict(row); item["aliases"] = " | ".join(item.get("aliases") or [])
            writer.writerow(item)

    report.update({"json": str(out), "csv": str(csv_out)})
    report_path = Path(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
