"""Read-only current CDB admission gate for four-player WTA doubles rankings.

A two-team canonical match is NOT proof of four named/individually identified
players. Never fill a team rank with an individual's historical doubles rank.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest
from tbt.data.wta_doubles_rank_history import WTADoublesRankHistory, OFFICIAL_DOUBLES_SHA256

YEAR = 2026
TOUR = "wta"
IDENTITY_KEYS = (
    ("team1_player_ids", "team2_player_ids"),
    ("doubles_team1_player_ids", "doubles_team2_player_ids"),
)
POTENTIAL_KEY_WORDS = ("team", "double", "partner", "participant", "player_id", "team_id")


def checksum(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def strict_four_player_ids(payload: dict) -> tuple[str, str, str, str] | None:
    """Only structured four DISTINCT player IDs. Never split fuzzy team names."""
    if not isinstance(payload, dict):
        return None
    for first_key, second_key in IDENTITY_KEYS:
        first, second = payload.get(first_key), payload.get(second_key)
        if not isinstance(first, list) or not isinstance(second, list):
            continue
        if len(first) != 2 or len(second) != 2:
            continue
        ids = first + second
        if not all(isinstance(v, str) and v.strip() and v == v.strip() for v in ids):
            continue
        if len(set(ids)) == 4:
            return tuple(ids)
    return None


def parse_context(raw, match_id) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, str):
        raise ValueError("Non-string provider context for " + str(match_id))
    try:
        obj = json.loads(raw, parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite provider JSON")))
    except (TypeError, ValueError) as e:
        raise ValueError("Invalid provider context for " + str(match_id)) from e
    if not isinstance(obj, dict):
        raise ValueError("Provider context must be object for " + str(match_id))
    return obj


def audit(source: Path, partition: Path, history_manifest: Path, output: Path) -> dict:
    if checksum(source) != OFFICIAL_DOUBLES_SHA256:
        raise ValueError("WTA official doubles supplement SHA mismatch")
    ranking = WTADoublesRankHistory.from_csv_gz(source)
    rank_rows = sum(len(v) for v in ranking._entries.values())
    if rank_rows != 19366:
        raise ValueError("Mapped WTA doubles source cardinality changed")
    year_meta = (load_manifest(history_manifest.parent).get("years") or {}).get(str(YEAR)) or {}
    if year_meta.get("asset") != partition.name or year_meta.get("sha256") != checksum(partition):
        raise ValueError("Current canonical year part does not match manifest")
    cols = ["match_id", "tour", "scheduled_at", "player1_id", "player2_id",
            "player1_name", "player2_name", "tournament_level", "provider_context_json"]
    df = pd.read_parquet(partition, columns=cols)
    if len(df) != int(year_meta.get("rows", -1)) or df["match_id"].isna().any():
        raise ValueError("Malformed canonical 2026 partition")
    if df["match_id"].astype(str).duplicated().any():
        raise ValueError("Canonical match id ambiguity")
    by_keys, hints, examples = Counter(), Counter(), Counter()
    summaries = Counter()
    for row in df.itertuples(index=False):
        summaries["canonical_matches_scanned"] += 1
        if str(row.tour).lower() != TOUR:
            continue
        summaries["wta_matches_scanned"] += 1
        context = parse_context(row.provider_context_json, row.match_id)
        names = (str(row.player1_name or ""), str(row.player2_name or ""))
        if any("/" in name or " & " in name or " / " in name for name in names):
            summaries["team_name_pattern_hints"] += 1
        if "double" in str(row.tournament_level or "").lower():
            summaries["doubles_tournament_level_hints"] += 1
        for key, val in context.items():
            # Enumerate ALL canonical provider-context top-level keys, not only
            # keys that look like person identifiers; preserve counts, not
            # source payload contents or guessed identities.
            by_keys["root:" + str(key) + ":" + type(val).__name__] += 1
            if any(word in key.lower() for word in POTENTIAL_KEY_WORDS):
                hints[key] += 1
        for side in ("homeTeam", "awayTeam"):
            obj = context.get(side)
            if isinstance(obj, dict):
                by_keys[side + ":dict"] += 1
                for key, val in obj.items():
                    by_keys[side + "." + str(key) + ":" + type(val).__name__] += 1
                    # A list of two individuals can be useful for a future
                    # source-specific ID crosswalk, but is NOT validated here.
                    if isinstance(val, list):
                        by_keys[side + "." + str(key) + ":list_len_" + str(len(val))] += 1
            else:
                by_keys[side + ":" + type(obj).__name__] += 1
        four = strict_four_player_ids(context)
        if four is not None:
            summaries["matches_with_structured_four_distinct_ids"] += 1
            by_keys["structured_four_ids_any_eligible_keys"] += 1
            if "double" in str(row.tournament_level or "").lower():
                summaries["four_ids_plus_doubles_tournament_hint"] += 1
        # Exactly four IDs alone do not validate the canonical-to-Sackmann
        # crosswalk, upstream player order, dates, match format or source rights.
    result = {
        "schema": 1,
        "status": "READ_ONLY_WTA_DOUBLES_FOUR_PLAYER_IDENTITY_AUDIT",
        "source_family": "official_wta_doubles_post_sackmann_2026",
        "source_sha256": OFFICIAL_DOUBLES_SHA256,
        "supplement_normalized_rows": rank_rows,
        "supplement_unique_sackmann_player_ids": len(ranking._entries),
        "year": YEAR,
        "canonical_partition_sha256": year_meta["sha256"],
        "counts": dict(summaries),
        "potential_provider_payload_key_counts": dict(hints.most_common(50)),
        "provider_payload_shape_counts": dict(by_keys.most_common(100)),
        "source_status": "SHA_verified_official_WTA_doubles_supplement_stored_in_private_research",
        "rank_join_policy": "four_explicit_player_ids + validated_canonical_to_sackmann_crosswalk + prior_week_asof + upstream team_side + rights",
        "exact_verified_four_id_crosswalks_to_sackmann": None,
        "proven_new_canonical_individual_doubles_rank_values": 0,
        "write_authorized": False,
        "canonical_mutated": False,
        "provider_api_requests": 0,
        "production_model_training": False,
        "production_model_promotion": False,
        "limitations": [
            "team-names or participant-side IDs are not four original independent player IDs",
            "structured four IDs alone are identity candidates, not complete proofs",
            "published historical doubles rank must be earlier than match date",
            "no newly requested canonical field and no production write in read-only audit",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--year-partition", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.source,args.year_partition,args.manifest,args.output),sort_keys=True))


if __name__ == "__main__":
    main()
