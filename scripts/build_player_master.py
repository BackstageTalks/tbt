"""Build a production player master from canonical history and optional player profiles."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.services.countries import normalize_country_code


def _country_from_payload(payload: dict, player1: bool) -> str:
    if not isinstance(payload, dict):
        return ""
    keys = ("homeTeam", "home_team", "player1", "participant1", "player_1") if player1 else ("awayTeam", "away_team", "player2", "participant2", "player_2")
    side = next((payload.get(k) for k in keys if isinstance(payload.get(k), dict)), {})
    candidates = []
    if isinstance(side, dict):
        candidates.extend([side.get("country_code"), side.get("countryCode"), side.get("countryAlpha2"), side.get("countryAlpha3"), side.get("country_code2"), side.get("country_code3")])
        country = side.get("country")
        if isinstance(country, dict):
            candidates.extend([country.get("alpha2"), country.get("alpha3"), country.get("code"), country.get("iso2"), country.get("iso3")])
    for value in candidates:
        code = normalize_country_code(value)
        if code:
            return code
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default=".cache/tbt/history")
    parser.add_argument("--profiles", default="")
    parser.add_argument("--out", default=".cache/tbt/player_master.json")
    parser.add_argument("--csv", dest="csv_out", default=".cache/tbt/player_master.csv")
    args = parser.parse_args()

    matches = load_partitions(Path(args.history_dir))
    profile_map = {}
    if args.profiles and Path(args.profiles).is_file():
        payload = json.loads(Path(args.profiles).read_text(encoding="utf-8"))
        rows = payload.get("players") if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            profile_map = {str(row.get("id") or ""): row for row in rows if isinstance(row, dict) and row.get("id") not in (None, "")}
        elif isinstance(rows, dict):
            profile_map = {str(k): v for k, v in rows.items() if isinstance(v, dict)}

    master: dict[tuple[str, str], dict] = {}
    aliases = defaultdict(set)
    for match in matches:
        for idx in (1, 2):
            pid = str(getattr(match, f"player{idx}_id") or "").strip()
            if not pid:
                continue
            tour = str(match.tour or "").lower()
            key = (tour, pid)
            name = str(getattr(match, f"player{idx}_name") or "").strip()
            rank = getattr(match, f"player{idx}_rank")
            aliases[key].add(name)
            row = master.setdefault(key, {
                "player_id": pid, "tour": tour, "name": name,
                "country_code": "", "latest_rank": None,
                "first_seen": match.scheduled_at.isoformat(), "last_seen": match.scheduled_at.isoformat(),
                "matches_seen": 0, "aliases": [],
            })
            row["matches_seen"] += 1
            if match.scheduled_at.isoformat() < row["first_seen"]:
                row["first_seen"] = match.scheduled_at.isoformat()
            if match.scheduled_at.isoformat() >= row["last_seen"]:
                row["last_seen"] = match.scheduled_at.isoformat()
                if name:
                    row["name"] = name
                if rank not in (None, ""):
                    row["latest_rank"] = int(rank)
                code = _country_from_payload(match.provider_payload, player1=idx == 1)
                if code:
                    row["country_code"] = code

    for (tour, pid), row in master.items():
        profile = profile_map.get(pid, {})
        if profile:
            code = normalize_country_code(profile.get("country_code") or profile.get("country_code3"))
            if code:
                row["country_code"] = code
            for source, target in (("rank", "latest_rank"), ("hand", "hand"), ("birth_date", "birth_date"), ("height_cm", "height_cm"), ("photo_file", "photo_file")):
                if profile.get(source) not in (None, ""):
                    row[target] = profile[source]
            if profile.get("name"):
                row["name"] = str(profile["name"])
        row["aliases"] = sorted(x for x in aliases[(tour, pid)] if x and x != row["name"])

    rows = sorted(master.values(), key=lambda r: (r["tour"], r["name"].lower(), r["player_id"]))
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": 1, "players": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_out = Path(args.csv_out); csv_out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["player_id", "tour", "name", "country_code", "latest_rank", "hand", "birth_date", "height_cm", "first_seen", "last_seen", "matches_seen", "aliases"]
    with csv_out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            item = dict(row); item["aliases"] = " | ".join(item.get("aliases") or [])
            writer.writerow(item)
    missing_country = sum(not row.get("country_code") for row in rows)
    print(json.dumps({"players": len(rows), "missing_country": missing_country, "country_coverage": round(1 - missing_country / max(1, len(rows)), 4), "json": str(out), "csv": str(csv_out)}, indent=2))


if __name__ == "__main__":
    main()
