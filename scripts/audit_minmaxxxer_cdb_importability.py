#!/usr/bin/env python3
"""Read-only pinned MinMaxxxer/Flashscore-versus-CDB event and NULL-cell audit.

This module never mutates CDB, imports odds, or establishes cross-provider
identity from abbreviated names alone. A candidate needs an independently
accepted Flashscore event bridge, bounded (24h max) UTC, both player sides, winner,
complete canonical score, and all four matching canonical ace/DF counts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path

from import_offline_linked_serve_return import ALLOWED, _signature
from link_offline_serve_return import _norm_round
from link_uploaded_flashscore_verified import INDEX_SHA, norm, short_matches, utc, read_gzip
from verify_uploaded_2025_2026_raw_parity import rates
from tbt.data.history_snapshot import load_snapshot

FILES = {
    "atp_matches_2025.csv": ("ATP", 832161),
    "wta_matches_2025.csv": ("WTA", 793938),
    "atp_matches_2026.csv": ("ATP", 773871),
    "wta_matches_2026.csv": ("WTA", 739770),
}
REQUIRED = {"match_id", "tourney_name", "surface", "round", "best_of",
            "winner_name", "loser_name", "score", "start_time_utc",
            "w_ace", "w_df", "l_ace", "l_df", "w_svpt", "w_1stIn",
            "w_1stWon", "w_2ndWon", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon"}
STAT_COUNTS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "bpSaved", "bpFaced")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_stats(row):
    # A nonnegative integer (including zero) is observed, not imputed.
    for prefix in ("w", "l"):
        observed = {}
        for field in STAT_COUNTS:
            raw = str(row.get(f"{prefix}_{field}") or "").strip()
            if not raw:
                return None
            if not raw.isascii() or not raw.isdecimal():
                return None
            observed[field] = int(raw)
        n, a, b, c = (observed[x] for x in ("svpt", "1stIn", "1stWon", "2ndWon"))
        if (n < 1 or a > n or b > a or c > n - a
                or observed["bpSaved"] > observed["bpFaced"]
                or observed["ace"] > n or observed["df"] > n
                or any(x > 500 for x in observed.values())):
            return None
    w, l = rates(row, "w"), rates(row, "l")
    if not all(k in w and k in l for k in ("aces", "double_faults", "service_points_won")):
        return None
    for first, opposite in ((w, l), (l, w)):
        first["return_points_won"] = 1.0 - opposite["service_points_won"]
        faced = int(row["l_bpFaced"] if first is w else row["w_bpFaced"])
        saved = int(row["l_bpSaved"] if first is w else row["w_bpSaved"])
        if faced > 0:
            first["break_point_return_win"] = (faced - saved) / faced
    if any(k not in ALLOWED for k in
           [f"p1_{k}" for k in w] + [f"p2_{k}" for k in l]):
        raise ValueError("Unexpected unsupported statistic")
    return w, l


def completed_score(value, best_of):
    import re
    try:
        max_sets = int(best_of)
    except (ValueError, TypeError):
        return None
    if max_sets not in (3, 5):
        return None
    tokens = str(value or "").strip().split()
    if not 2 <= len(tokens) <= max_sets:
        return None
    sets = []
    for token in tokens:
        m = re.fullmatch(r"(\d+)-(\d+)(?:\((\d+)\))?", token)
        if m is None:
            return None
        a, b = int(m[1]), int(m[2])
        bigger, smaller = max(a, b), min(a, b)
        if (bigger == 6 and smaller <= 4) or (bigger == 7 and smaller in (5, 6)):
            if smaller == 6 and m[3] is None:
                return None
            sets.append((a, b))
        else:
            return None
    winner_sets = sum(a > b for a, b in sets)
    loser_sets = len(sets) - winner_sets
    if winner_sets != max_sets // 2 + 1 or loser_sets >= winner_sets:
        return None
    if len(sets) != winner_sets + loser_sets:
        return None
    return sets


def audit(source, index_file, history, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    source = Path(source)
    history = Path(history)
    index_file = Path(index_file)
    if sha(index_file) != INDEX_SHA:
        raise ValueError("Independent native-event index SHA mismatch")
    manifest = json.loads((history / "history_manifest.json").read_text())["years"]
    bundle = json.loads((history / "_tbt_bundle_manifest.json").read_text())["files"]
    canonical = {}
    for year in (2024, 2025, 2026):
        path = history / f"history-{year}.parquet"
        digest = sha(path)
        if digest != manifest[str(year)]["sha256"] or digest != bundle[path.name]["sha256"]:
            raise ValueError("Current canonical SHA or manifest mismatch")
        for match in load_snapshot(path):
            mid = str(match.match_id)
            if mid in canonical:
                raise ValueError("Duplicated canonical match ID")
            canonical[mid] = match
    index = defaultdict(list)
    for row in read_gzip(index_file):
        if not isinstance(row, dict):
            raise ValueError("Invalid native-event index row")
        if row.get("event_id"):
            index[str(row["event_id"])].append(row)
    counts = Counter()
    output = []
    staged_ids = set()
    sha_sources = {}
    source_ids = set()
    for file, (tour, expected_bytes) in FILES.items():
        path = source / file
        if not path.is_file() or path.stat().st_size != expected_bytes:
            raise ValueError("Pinned source bytes / inventory mismatch: " + file)
        sha_sources[file] = sha(path)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
                raise ValueError("Unexpected source CSV schema: " + file)
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError("Duplicate source CSV fields")
            for src in reader:
                counts["source_rows"] += 1
                if None in src:
                    counts["malformed_rows"] += 1
                    continue
                event = str(src.get("match_id") or "")
                key = (tour, event)
                if not event or key in source_ids:
                    counts["missing_or_duplicate_source_event"] += 1
                    continue
                source_ids.add(key)
                stat_pair = clean_stats(src)
                if stat_pair is None:
                    counts["invalid_or_incomplete_source_stats"] += 1
                    continue
                counts["source_rows_stat_quality_pass"] += 1
                candidates = index.get(event, [])
                if len(candidates) != 1:
                    counts["native_event_index_absent_or_ambiguous"] += 1
                    continue
                counts["unique_native_event_index_hits"] += 1
                ix = candidates[0]
                link = ix.get("link")
                if (not ix.get("canonical_match_id") or not isinstance(link, dict)
                        or link.get("accepted") is not True
                        or link.get("orientation") not in ("direct", "swapped")):
                    counts["index_not_independently_accepted"] += 1
                    continue
                m = canonical.get(str(ix["canonical_match_id"]))
                if m is None:
                    counts["index_not_in_2024_2026_cdb"] += 1
                    continue
                counts["indexed_current_cdb_matches"] += 1
                when = utc(src.get("start_time_utc"))
                indexed_time = utc(ix.get("start_utc"))
                canonical_time = utc(m.scheduled_at)
                if when is None or indexed_time is None or canonical_time is None:
                    counts["missing_or_unparseable_time"] += 1
                else:
                    if when == indexed_time:
                        counts["time_source_index_exact"] += 1
                    if when == canonical_time:
                        counts["time_source_cdb_exact"] += 1
                    if indexed_time == canonical_time:
                        counts["time_index_cdb_exact"] += 1
                    if when.date() == indexed_time.date():
                        counts["time_source_index_same_utc_date"] += 1
                    if when.date() == canonical_time.date():
                        counts["time_source_cdb_same_utc_date"] += 1
                    if indexed_time.date() == canonical_time.date():
                        counts["time_index_cdb_same_utc_date"] += 1
                    if when.date() == indexed_time.date() == canonical_time.date():
                        counts["time_all_three_same_utc_date"] += 1
                    if (max(when, indexed_time, canonical_time)
                            - min(when, indexed_time, canonical_time)).total_seconds() <= 86400:
                        counts["time_all_three_within_24h"] += 1
                    if str(ix.get("tour")).upper() == tour == str(m.tour).upper():
                        counts["tour_all_three_same"] += 1
                if (str(m.tour).upper() != tour or str(ix.get("tour")).upper() != tour
                        or when is None or indexed_time is None or canonical_time is None
                        or (max(when, indexed_time, canonical_time)
                            - min(when, indexed_time, canonical_time)).total_seconds() > 86400):
                    counts["time_or_tour_mismatch"] += 1
                    continue
                if not (when == indexed_time == canonical_time):
                    # Timing tolerance is ONLY safe after the subsequent native
                    # event, both source sides, winner, round, complete canonical
                    # scoreboard, four original ace/DF witnesses and all-stat
                    # no-conflict tests. Never output a partial candidate.
                    counts["time_bounded_clock_drift_needs_extra_corrob"] += 1
                if str(m.status).lower() not in ("finished", "completed", "ended"):
                    counts["canonical_not_completed"] += 1
                    continue
                wname, lname = src["winner_name"], src["loser_name"]
                n1, n2 = norm(ix.get("player1_source")), norm(ix.get("player2_source"))
                if not n1 or n1 == n2 or {n1, n2} != {norm(wname), norm(lname)}:
                    counts["native_event_two_player_mismatch"] += 1
                    continue
                winner_first_index = n1 == norm(wname)
                winner_is_p1 = (winner_first_index if link["orientation"] == "direct"
                                else not winner_first_index)
                cwin = m.player1_name if winner_is_p1 else m.player2_name
                clos = m.player2_name if winner_is_p1 else m.player1_name
                if not short_matches(cwin, wname) or not short_matches(clos, lname):
                    counts["independent_full_names_mismatch"] += 1
                    continue
                if str(m.winner_id) != str(m.player1_id if winner_is_p1 else m.player2_id):
                    counts["canonical_winner_mismatch"] += 1
                    continue
                if (norm(m.surface) != norm(src["surface"])
                        or _norm_round(m.round_name) != _norm_round(src["round"])
                        or m.best_of is None or int(m.best_of) != int(src["best_of"])):
                    counts["surface_round_or_format_mismatch"] += 1
                    continue
                label = norm(src["tourney_name"])
                if not label or (label != norm(ix.get("tournament"))
                                     and norm(ix.get("tournament")) != norm(m.tournament)):
                    counts["event_name_not_corroborated"] += 1
                    continue
                sets = completed_score(src["score"], src["best_of"])
                if not sets:
                    counts["source_score_not_complete_supported_format"] += 1
                    continue
                original = dict(m.stats or {})
                expected = {}
                for setno, (w, l) in enumerate(sets, 1):
                    for side, games in (("p1", w if winner_is_p1 else l),
                                        ("p2", l if winner_is_p1 else w)):
                        expected[f"{side}_set{setno}_games"] = games
                if any(original.get(k) is None or float(original[k]) != v
                       for k, v in expected.items()):
                    counts["full_canonical_score_not_verified"] += 1
                    continue
                wstats, lstats = stat_pair
                proposals = {}
                for side, fields in (("p1" if winner_is_p1 else "p2", wstats),
                                     ("p2" if winner_is_p1 else "p1", lstats)):
                    for name, value in fields.items():
                        proposals[f"{side}_{name}"] = float(value)
                four = ("p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults")
                if not all(k in proposals and original.get(k) is not None
                           and math.isclose(float(original[k]), proposals[k],
                                            abs_tol=1e-8, rel_tol=0) for k in four):
                    counts["four_count_identity_witness_missing"] += 1
                    continue
                counts["cross_source_match_fully_verified"] += 1
                if any(original.get(k) is not None and
                       not math.isclose(float(original[k]), v, abs_tol=1e-6, rel_tol=0)
                       for k, v in proposals.items()):
                    counts["canonical_existing_stat_conflict"] += 1
                    continue
                delta = {k: v for k, v in proposals.items() if original.get(k) is None}
                if not delta:
                    counts["already_complete"] += 1
                    continue
                mid = str(m.match_id)
                if mid in staged_ids:
                    counts["duplicate_canonical_target"] += 1
                    continue
                staged_ids.add(mid)
                counts["eligible_matches"] += 1
                counts["eligible_new_cells"] += len(delta)
                output.append({
                    "schema": 1, "match_id": mid, "canonical": _signature(m),
                    "incoming_stats": delta, "import_ready": True,
                    "source": {
                        "dataset": "minmaxxxer/atp-wta-matches-with-odds",
                        "source_file": file, "source_sha256": sha_sources[file],
                        "independent_flashscore_index_sha256": INDEX_SHA,
                        "proof": "native_event_three_clocks_within_24h_both_players_winner_full_score_four_counts",
                    },
                })
    stage = out / "eligible-private.jsonl"
    with stage.open("x", encoding="utf-8") as stream:
        for row in output:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema": 1, "status": "READ_ONLY_HF_TO_CURRENT_CDB_NULL_AUDIT",
        "canonical_rows_checked": len(canonical),
        "pinned_source_sha256": dict(sorted(sha_sources.items())),
        "index_sha256": INDEX_SHA,
        "counts": dict(sorted(counts.items())),
        "stage_sha256": sha(stage), "stage_rows": len(output),
        "production_mutated": False, "writer_executed": False,
        "paid_api_requests": 0, "odds_imported": 0,
        "restrictions": "Never trust vendor source IDs as canonical; no name-only identity; PIT odds excluded.",
    }
    (out / "aggregate-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("HF_CDB_AGGREGATE", json.dumps({
        "source_rows": counts["source_rows"],
        "source_qa": counts["source_rows_stat_quality_pass"],
        "index_hits": counts["unique_native_event_index_hits"],
        "canonical_matches": counts["indexed_current_cdb_matches"],
        "fully_verified": counts["cross_source_match_fully_verified"],
        "eligible_matches": counts["eligible_matches"],
        "eligible_new_cells": counts["eligible_new_cells"],
        "reasons": dict(sorted(counts.items())),
    }, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ("source-dir", "index", "history-dir", "out"):
        parser.add_argument("--" + name, required=True)
    a = parser.parse_args()
    audit(a.source_dir, a.index, a.history_dir, a.out)


if __name__ == "__main__":
    main()
