#!/usr/bin/env python3
"""Count-only, read-only WTA 2024 TennisExplorer vs verified canonical partition.

This script deliberately produces no match-link crosswalk, new matches,
write package, model features or player-level public artifact.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import tarfile
import unicodedata

import pandas as pd

SOURCE_MEMBER = "data/tennisexplorer/results/wta-single/2024.csv"
CDB_COLUMNS = (
    "match_id", "tour", "scheduled_at", "player1_id", "player1_name",
    "player2_id", "player2_name", "winner_id", "tournament", "status"
)
SHA = re.compile(r"^[a-f0-9]{64}$")


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def norm(value: object) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value).strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def source_players(row: dict) -> tuple[str, str] | None:
    try:
        a, b = (json.loads(row["side1_players_json"]),
                json.loads(row["side2_players_json"]))
    except (KeyError, TypeError, ValueError):
        return None
    if not (isinstance(a, list) and isinstance(b, list) and
            len(a) == len(b) == 1):
        return None
    x, y = norm(a[0]), norm(b[0])
    if not x or not y or x == y:
        return None
    return x, y


def result_side(row: dict) -> int | None:
    a, b = (str(row.get("side1_sets_won") or "").strip(),
            str(row.get("side2_sets_won") or "").strip())
    if not (re.fullmatch("[0-3]", a) and re.fullmatch("[0-3]", b)):
        return None
    if a == b:
        return None
    if max(int(a), int(b)) < 2:
        return None
    return 1 if int(a) > int(b) else 2


def canonical_rows(frame: pd.DataFrame) -> list[dict]:
    missing = set(CDB_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError("Canonical missing columns " + repr(sorted(missing)))
    if frame["match_id"].duplicated().any():
        raise ValueError("Duplicate canonical match IDs; audit fails closed")
    return frame[list(CDB_COLUMNS)].to_dict(orient="records")


def compare(source: list[dict], canonical: list[dict]) -> dict:
    ix = defaultdict(list)
    canonical_count = 0
    for c in canonical:
        if str(c.get("tour") or "").lower() != "wta":
            continue
        canonical_count += 1
        n1, n2 = norm(c.get("player1_name")), norm(c.get("player2_name"))
        if not n1 or not n2 or n1 == n2:
            continue
        try:
            dt = pd.Timestamp(c["scheduled_at"]).date()
        except (ValueError, TypeError):
            continue
        key = frozenset((n1, n2))
        ix[key].append((dt, c, n1, n2))

    counts = Counter()
    proposals = []
    source_seen = set()
    for row in source:
        counts["source_rows"] += 1
        if row.get("category") != "wta-single" or str(row.get("tour") or "").lower() != "wta":
            counts["wrong_source_tour_or_category"] += 1
            continue
        sid = str(row.get("match_id") or "").strip()
        if not sid or sid in source_seen:
            counts["missing_or_duplicate_source_id"] += 1
            continue
        source_seen.add(sid)
        pp = source_players(row)
        if pp is None:
            counts["incomplete_source_player_identity"] += 1
            continue
        try:
            when = date.fromisoformat(str(row["date"]))
        except (KeyError, ValueError, TypeError):
            counts["invalid_source_date"] += 1
            continue
        if when.year != 2024:
            counts["wrong_source_year"] += 1
            continue
        src_winner = result_side(row)
        if src_winner is None:
            counts["unverifiable_source_winner"] += 1
            continue
        src_tournament = norm(row.get("tournament"))
        if not src_tournament:
            counts["missing_source_tournament"] += 1
            continue

        dated = [
            (c, n1, n2) for day, c, n1, n2 in ix.get(frozenset(pp), ())
            if abs((day - when).days) <= 1
        ]
        if not dated:
            counts["unmatched_exact_players_and_day"] += 1
            continue
        same_tournament = [
            (c, n1, n2) for c, n1, n2 in dated
            if norm(c.get("tournament")) == src_tournament
        ]
        if not same_tournament:
            counts["not_exact_tournament"] += 1
            continue
        if len(same_tournament) != 1:
            counts["ambiguous_canonical_events"] += 1
            continue
        c, n1, n2 = same_tournament[0]
        orientation = 1 if (pp[0], pp[1]) == (n1, n2) else 2
        expected_id = str(c["player1_id"] if (src_winner == orientation)
                          else c["player2_id"])
        actual = c.get("winner_id")
        actual_str = str(actual) if actual is not None and not pd.isna(actual) else ""
        if actual_str and actual_str != expected_id:
            counts["canonical_winner_conflicts"] += 1
            continue
        if not actual_str:
            counts["canonical_winner_null_research_only"] += 1
            # Never manufacture this as an approved missing field.
            continue
        counts["source_result_agrees_with_canonical_winner"] += 1
        proposals.append((sid, str(c["match_id"])))

    owners = Counter(c for _, c in proposals)
    collisions = {c for c, n in owners.items() if n > 1}
    counts["duplicate_canonical_claim_source_rows"] = sum(
        1 for _, c in proposals if c in collisions
    )
    counts["unique_match_winner_agreements"] = len(proposals) - counts["duplicate_canonical_claim_source_rows"]
    counts["canonical_wta_rows_in_partition"] = canonical_count
    counts["source_unique_ids"] = len(source_seen)
    return {
        "schema": 1,
        "source": "TennisExplorer WTA singles 2024",
        "result": "EXACT_NAME_DAY_TOURNAMENT_WINNER_MATCHING_READ_ONLY",
        "counts": dict(sorted(counts.items())),
        "matching_policy": "both full player names exact accent-folded; ±1 day; exact normalized tournament; unique candidate; source sets winner must agree with canonical ID",
        "exclusions": "no fuzzy names, no score completion guess, no weak linking, no doubles, no market timestamps, no training feature",
        "independently_approved_missing_cdb_cells": 0,
        "canonical_writes": 0,
        "model_training_or_promotion": False,
        "source_rights_proven": False,
        "source_proposals_exported": False,
    }



def _surname_initial(name: str, *, source: bool) -> tuple[str, str] | None:
    tokens = norm(name).split()
    if len(tokens) < 2:
        return None
    if source and len(tokens[-1]) == 1:
        family, initial = tokens[-2], tokens[-1]
    elif source and len(tokens[0]) == 1:
        family, initial = tokens[-1], tokens[0]
    else:
        family, initial = tokens[-1], tokens[0][0]
    if not family or not initial:
        return None
    return family, initial[0]


def name_format_diagnostics(source: list[dict], canonical: list[dict]) -> dict:
    """Aggregate research-only alternate-name hit rates, with no links exported.

    The surname+first-initial representation is NOT an independently proven
    player crosswalk. It is only a diagnostic to explain strict zero-overlap.
    """
    full_token_ix = defaultdict(list)
    initial_ix = defaultdict(list)
    for row in canonical:
        if str(row.get("tour") or "").lower() != "wta":
            continue
        a, b = norm(row.get("player1_name")), norm(row.get("player2_name"))
        if not a or not b or a == b:
            continue
        try:
            day = pd.Timestamp(row["scheduled_at"]).date()
        except (ValueError, TypeError):
            continue
        full_token_ix[frozenset((tuple(sorted(a.split())),
                                tuple(sorted(b.split()))))].append((day, row))
        # Both source and canonical providers sometimes reverse given/family
        # order. Index both structural interpretations only as weak diagnostics.
        ta, tb = a.split(), b.split()
        fa = {(ta[-1], ta[0][0]), (ta[0], ta[-1][0])} if len(ta) >= 2 else set()
        fb = {(tb[-1], tb[0][0]), (tb[0], tb[-1][0])} if len(tb) >= 2 else set()
        for ai in fa:
            for bi in fb:
                if ai != bi:
                    initial_ix[frozenset((ai, bi))].append((day, row))

    counts = Counter()
    for row in source:
        if row.get("category") != "wta-single":
            continue
        pp = source_players(row)
        if pp is None:
            continue
        counts["source_rows_with_two_source_player_names"] += 1
        if any(len(tok) == 1 for n in pp for tok in n.split()):
            counts["source_rows_containing_a_single_letter_token"] += 1
        try:
            day = date.fromisoformat(str(row["date"]))
        except (ValueError, KeyError, TypeError):
            continue
        fullkey = frozenset(tuple(sorted(name.split())) for name in pp)
        full_matches = [m for dt, m in full_token_ix.get(fullkey, ())
                        if abs((dt-day).days) <= 1]
        if full_matches:
            counts["unordered_full_token_pair_day_candidate_rows"] += 1
            if any(norm(m.get("tournament")) == norm(row.get("tournament"))
                   for m in full_matches):
                counts["unordered_full_token_pair_day_tournament_candidate_rows"] += 1

        si = tuple(_surname_initial(n, source=True) for n in pp)
        if None in si or si[0] == si[1]:
            continue
        abbr_candidates = [m for dt, m in initial_ix.get(frozenset(si), ())
                           if abs((dt-day).days) <= 1]
        # A canonical match can be reachable through several name-order forms.
        # Count unique canonical identities rather than repeated index entries.
        abbr_matches = list({str(m.get("match_id")): m for m in abbr_candidates}.values())
        if abbr_matches:
            counts["surname_initial_pair_day_candidate_rows_research_only"] += 1
            agree = [m for m in abbr_matches
                     if norm(m.get("tournament")) == norm(row.get("tournament"))]
            if agree:
                counts["surname_initial_pair_day_tournament_candidate_rows_research_only"] += 1
                if len(agree) == 1:
                    counts["surname_initial_unique_match_candidate_rows_research_only"] += 1
            elif not full_matches:
                counts["surname_initial_day_only_tournament_mismatch_rows"] += 1
    return {
        "counts": dict(sorted(counts.items())),
        "identity_policy": "RESEARCH_ONLY; surname and first initial are not independently verified source player IDs",
        "canonical_link_approved": False,
        "new_cdb_cells_approved": 0,
        "player_id_crosswalk_exported": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--source-sha256", required=True)
    ap.add_argument("--canonical", type=Path, required=True)
    ap.add_argument("--canonical-sha256", required=True)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    for label, value, path in (
        ("source", args.source_sha256, args.source),
        ("canonical", args.canonical_sha256, args.canonical),
    ):
        if not SHA.fullmatch(value) or digest(path) != value:
            raise SystemExit(label + " SHA256 mismatch")
    bundle = json.loads(args.bundle.read_text())
    expected = (bundle.get("files") or {}).get("history-2024.parquet") or {}
    if expected.get("sha256") != args.canonical_sha256:
        raise SystemExit("Canonical release bundle digest differs; BLOCK")
    with tarfile.open(args.source, "r:gz") as tar:
        found = tar.getmember(SOURCE_MEMBER)
        if not found.isfile() or found.size > 100_000_000:
            raise SystemExit("Unsafe source member")
        stream = tar.extractfile(found)
        if stream is None:
            raise SystemExit("Missing source result CSV")
        with stream, io.TextIOWrapper(stream, encoding="utf-8-sig", newline="") as text:
            source = list(csv.DictReader(text))
    frame = pd.read_parquet(args.canonical, columns=list(CDB_COLUMNS))
    report = compare(source, canonical_rows(frame))
    report["name_format_diagnostics"] = name_format_diagnostics(source, canonical_rows(frame))
    report["verified_source_sha256"] = args.source_sha256
    report["verified_current_2024_cdb_sha256"] = args.canonical_sha256
    report["canonical_rows_in_year"] = len(frame)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("WTA_SINGLES_2024_CANONICAL_OVERLAP", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
