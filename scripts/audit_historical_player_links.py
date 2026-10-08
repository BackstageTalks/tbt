"""Read-only evidence audit for historical import identities vs canonical provider IDs.

Downloads only 2020-2026 history partitions from the immutable, checksum
manifest-protected private release. Never writes canonical history or models.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
PAIRS = {
    "Cameron Norrie": ("atp", "95935", "hist-js:atp:N771"),
    "Dalibor Svrcina": ("atp", "260122", "hist-js:atp:207494"),
}
COLUMNS = [
    "match_id", "tour", "scheduled_at", "player1_id", "player1_name",
    "player2_id", "player2_name", "winner_id", "tournament",
    "round_name", "surface", "status", "stats_json",
]


def download(name: str, directory: Path) -> Path:
    subprocess.run([
        "gh", "release", "download", TAG, "--repo", REPO,
        "--pattern", name, "--dir", str(directory),
        "--clobber",
    ], check=True, capture_output=True, text=True, timeout=120)
    path = directory / name
    if not path.is_file():
        raise RuntimeError(f"Missing release asset: {name}")
    return path


def norm(value: object) -> str:
    import unicodedata
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    return " ".join("".join(ch if ch.isalnum() else " " for ch in value if not unicodedata.combining(ch)).split())


def load(directory: Path) -> tuple[list[dict], dict]:
    bundle = json.loads(download("_tbt_bundle_manifest.json", directory).read_text())
    manifest = json.loads(download("history_manifest.json", directory).read_text())
    assert isinstance(bundle.get("files"), dict) and isinstance(manifest.get("years"), dict)
    records = []
    inventory = {}
    for year in range(2020, 2027):
        meta = manifest["years"].get(str(year))
        if not isinstance(meta, dict):
            raise RuntimeError(f"Missing canonical manifest year: {year}")
        name = str(meta.get("asset") or f"history-{year}.parquet")
        expected = bundle["files"].get(name, {}).get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            raise RuntimeError(f"Missing checksum for {name}")
        path = download(name, directory)
        received = sha256(path.read_bytes()).hexdigest()
        if received != expected:
            raise RuntimeError(f"Checksum mismatch for {name}")
        data = pd.read_parquet(path, columns=COLUMNS).to_dict(orient="records")
        records.extend(data)
        inventory[str(year)] = {"rows": len(data), "sha256": received}
        path.unlink()
    return records, inventory


def side(row: dict, candidate: str) -> dict | None:
    if row.get("player1_id") == candidate:
        return {"name": row["player1_name"], "opponent": row["player2_name"],
                "opponent_id": row["player2_id"], "won": str(row["winner_id"]) == candidate}
    if row.get("player2_id") == candidate:
        return {"name": row["player2_name"], "opponent": row["player1_name"],
                "opponent_id": row["player1_id"], "won": str(row["winner_id"]) == candidate}
    return None


def slim(row: dict, candidate: str) -> dict:
    item = side(row, candidate)
    return {
        "match_id": str(row["match_id"]), "date": str(row["scheduled_at"])[:10],
        "name": item["name"], "opponent": item["opponent"],
        "opponent_id": item["opponent_id"], "won": item["won"],
        "tournament": str(row.get("tournament") or ""),
        "surface": str(row.get("surface") or ""),
        "round": str(row.get("round_name") or ""),
        "has_stats": bool(str(row.get("stats_json") or "") not in ("", "{}","None")),
    }


def evidence(records: list[dict], provider: str, historical: str) -> dict:
    main = [slim(r, provider) for r in records if side(r, provider)]
    older = [slim(r, historical) for r in records if side(r, historical)]
    main_by_date = defaultdict(list)
    for row in main:
        main_by_date[row["date"]].append(row)
    matches, potential_conflicts = [], []
    for old in older:
        candidates = [
            current for current in main_by_date.get(old["date"], [])
            if norm(current["opponent"]) == norm(old["opponent"])
        ]
        for candidate in candidates:
            same_tournament = norm(candidate["tournament"]) == norm(old["tournament"])
            same_winner = candidate["won"] == old["won"]
            same_surface = norm(candidate["surface"]) == norm(old["surface"])
            detail = {"provider_match_id": candidate["match_id"],
                      "historical_match_id": old["match_id"],
                      "date": old["date"],
                      "opponent": old["opponent"],
                      "tournament_match": same_tournament,
                      "winner_match": same_winner,
                      "surface_match": same_surface}
            if len(candidates)==1 and all((same_tournament, same_winner, same_surface)):
                matches.append(detail)
            else:
                potential_conflicts.append(detail)
    provider_names = Counter(row["name"] for row in main)
    historical_names = Counter(row["name"] for row in older)
    provider_opp = {norm(row["opponent"]) for row in main}
    old_opp = {norm(row["opponent"]) for row in older}
    return {
        "provider_id": provider, "historical_id": historical,
        "provider_matches": len(main), "historical_matches": len(older),
        "provider_names": provider_names.most_common(5),
        "historical_names": historical_names.most_common(5),
        "historical_years": dict(Counter(x["date"][:4] for x in older)),
        "provider_years": dict(Counter(x["date"][:4] for x in main)),
        "common_opponent_names": len(provider_opp & old_opp),
        "unique_exact_overlap": matches[:20], "overlap_count": len(matches),
        "conflict_count": len(potential_conflicts),
        "conflict_examples": potential_conflicts[:10],
        "historical_examples": older[:8],
        "provider_examples": main[-4:],
        "scope": "only canonical history years 2020-2026",
        # A zero conflict count alone never proves identity. Require positive
        # independent identical-match evidence before proposing a crosswalk.
        "link_gate": "candidate_review" if len(matches)>=2 and not potential_conflicts else "unverified_quarantine",
    }


def main():
    with tempfile.TemporaryDirectory(prefix="blinq-identity-audit-") as root:
        rows, inventory = load(Path(root))
    print("CANONICAL_SOURCE", json.dumps({"release": TAG, "rows": len(rows),
                                          "years": inventory}, ensure_ascii=False), flush=True)
    for title, (tour, primary, scoped) in PAIRS.items():
        subset = [r for r in rows if str(r.get("tour") or "").lower()==tour]
        result = evidence(subset, primary, scoped)
        print("IDENTITY_PAIR", title, json.dumps(result, ensure_ascii=False, default=str), flush=True)
    print("IDENTITY_AUDIT_COMPLETE read_only=true api_requests=0 canonical_writes=0", flush=True)


if __name__ == "__main__":
    main()
