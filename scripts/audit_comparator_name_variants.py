"""Read-only full-directory audit of comparator name variants.

Uses the checksum-verified directory emitted by diagnose_comparator_snapshot in
PR CI; never changes canonical IDs, model weights, or source datasets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.data.player_identity import normalize_player_name
from tbt.services.comparator_runtime import (
    _abbreviated_name_key,
    _full_name_key,
    _safe_abbreviation_target,
    search_players,
)


def audit(players: list[dict]) -> dict:
    full = defaultdict(list)
    same_name = defaultdict(list)
    for row in players:
        tour = str(row.get("tour") or "").lower()
        if not row.get("player_id") or tour not in {"atp", "wta"}:
            continue
        name = normalize_player_name(row.get("name"))
        if name:
            same_name[tour, name].append(row)
        key = _full_name_key(row.get("name"))
        if key:
            full[tour, key].append(row)

    counts = Counter()
    examples = defaultdict(list)
    for row in players:
        tour = str(row.get("tour") or "").lower()
        key = _abbreviated_name_key(row.get("name"))
        if key is None or tour not in {"atp", "wta"}:
            continue
        counts["abbreviated_rows"] += 1
        matches = full[tour, key]
        distinct = {str(p["player_id"]): p for p in matches}
        if not distinct:
            label = "no_full_candidate"
        elif len(distinct) != 1:
            label = "ambiguous_full_candidates"
        elif _safe_abbreviation_target(row, matches) is not None:
            label = "safe_to_display_full_name"
        else:
            label = "weak_evidence_keep_distinct"
        counts[label] += 1
        if len(examples[label]) < 12:
            examples[label].append({
                "short_name": row.get("name"), "short_id": str(row.get("player_id")),
                "tour": tour, "full_candidates": [
                    {"name": p.get("name"), "id": str(p.get("player_id"))}
                    for p in matches[:4]
                ],
            })
        if label == "safe_to_display_full_name":
            mapped = search_players(
                {"players": players}, str(row.get("name")), tour=tour, limit=25
            )
            target = next(iter(distinct))
            if not mapped or mapped[0].get("player_id") != target:
                counts["search_contract_failures"] += 1
    for group in same_name.values():
        distinct = {str(p.get("player_id")) for p in group}
        if len(distinct) > 1:
            counts["same_spelling_multi_id_groups"] += 1
            counts["same_spelling_multi_id_rows"] += len(distinct)
            if len(examples["same_spelling_multi_id"]) < 10:
                examples["same_spelling_multi_id"].append({
                    "name": group[0].get("name"),
                    "tour": group[0].get("tour"),
                    "ids": sorted(distinct)[:4],
                })
    counts["directory_players"] = len(players)
    counts["atp_players"] = sum(str(p.get("tour")).lower() == "atp" for p in players)
    counts["wta_players"] = sum(str(p.get("tour")).lower() == "wta" for p in players)
    return {"counts": dict(counts), "examples": dict(examples)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--directory", type=Path,
        default=Path("/tmp/blinq-comparator-readonly-audit/comparator-players.json"),
    )
    args = parser.parse_args()
    payload = args.directory.read_bytes()
    directory = json.loads(payload)
    rows = directory.get("players")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Missing canonical directory")
    report = audit(rows)
    report["directory_sha256"] = hashlib.sha256(payload).hexdigest()
    report["generated_at"] = directory.get("generated_at")
    print("COMPARATOR_NAME_VARIANTS_AUDIT " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    if report["counts"].get("search_contract_failures"):
        raise RuntimeError("Verified full-name replacements did not survive search")


if __name__ == "__main__":
    main()
