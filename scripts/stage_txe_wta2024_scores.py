"""Source-byte pinned TennisExplorer WTA 2024 score enrichment for existing CDB matches.

Uses exact full-name match-detail anchors to construct a source player-slug ->
canonical player-ID map, then accepts only uniquely corroborated complete
matches with day, tournament, winning side, and result-set consistency.
All candidate stats are POSTMATCH historical inputs for subsequent matches.
No CDB, release, model or provider writes occur in this module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tarfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.offline_odds import tournament_score
from audit_tennisexplorer_wta2024_cdb_overlap import norm, result_side

YEAR = int(os.environ.get("BLINQ_SCORE_YEAR", "2024"))
TOUR = os.environ.get("BLINQ_SCORE_TOUR", "wta").lower()
SOURCE_SHA = os.environ.get("BLINQ_SCORE_SOURCE_SHA", "27c779c73bcfaf089e362f3480c4201f032e15fefbc3a0fadaa39bfce9f5956b")
if YEAR not in (2023, 2024, 2025, 2026) or TOUR not in ("wta", "atp") or not re.fullmatch(r"[a-f0-9]{64}", SOURCE_SHA):
    raise ValueError("Only pinned, verified TennisExplorer tour-year source packages are supported")
RESULT_MEMBER = f"data/tennisexplorer/results/{TOUR}-single/{YEAR}.csv"
DETAIL_MEMBER = f"data/tennisexplorer/enrichment/{TOUR}-single/{YEAR}.jsonl"
FIELD_NAMES = frozenset(("total_sets", "total_games", "deciding_set",
    "p1_first_set_won", "p2_first_set_won", "p1_second_set_won",
    "p2_second_set_won", "p1_games_won", "p2_games_won",
    "p1_sets_won", "p2_sets_won"))
REGULAR_SET = re.compile(r"^([0-7])(?:\(\d{1,3}\))?$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,100}$")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(2 ** 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_archive(path, expected_sha=SOURCE_SHA):
    if sha256(path) != expected_sha:
        raise ValueError("Source SHA-256 mismatch")
    with tarfile.open(path, "r:gz") as tar:
        names = tar.getmembers()
        if len(names) > 20000 or sum(x.size for x in names) > 4 * 1024 ** 3:
            raise ValueError("Unsafe archive dimensions")
        if any(not x.isfile() or x.issym() or x.islnk()
               or x.name.startswith("/") or ".." in x.name.split("/") for x in names):
            raise ValueError("Unsafe archive members")
        if len({x.name for x in names}) != len(names):
            raise ValueError("Duplicate archive member")
        entries = {x.name: x for x in names}
        if RESULT_MEMBER not in entries or DETAIL_MEMBER not in entries:
            raise ValueError("Missing original match/detail members")
        if entries[RESULT_MEMBER].size > 256 * 1024 ** 2 or entries[DETAIL_MEMBER].size > 768 * 1024 ** 2:
            raise ValueError("Source members too large")
        result = tar.extractfile(entries[RESULT_MEMBER])
        details = tar.extractfile(entries[DETAIL_MEMBER])
        if result is None or details is None:
            raise ValueError("Unextractable archive")
        with io.TextIOWrapper(result, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        with io.TextIOWrapper(details, encoding="utf-8-sig") as f:
            enriched = [json.loads(line) for line in f if line.strip()]
    if not rows or not enriched or (YEAR == 2024 and TOUR == "wta" and (len(rows) != 45143 or len(enriched) != 8524)):
        raise ValueError("Original source year missing or pinned 2024 cardinality drift")
    return rows, enriched


def player_slug(url):
    p = urlparse(str(url or ""))
    if p.netloc.lower() not in {"tennisexplorer.com", "www.tennisexplorer.com"}:
        return None
    parts = p.path.strip("/").split("/")
    if len(parts) != 2 or parts[0] != "player" or not SLUG.fullmatch(parts[1]):
        return None
    return parts[1]


def full_name(value):
    value = norm(value)
    tokens = value.split()
    # Abbreviated names are never an independent exact-name anchor.
    return tuple(sorted(tokens)) if len(tokens) >= 2 and min(map(len, tokens)) >= 2 else None


def result_slugs(row):
    try:
        a = json.loads(row.get("side1_player_slugs_json", ""))
        b = json.loads(row.get("side2_player_slugs_json", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b) != 1:
        return None
    if len(a) != 1 or len(b) != 1 or not all(isinstance(x, str) and SLUG.fullmatch(x) for x in (a[0], b[0])):
        return None
    return a[0], b[0]


def score_values(row):
    if result_side(row) is None:
        return None
    try:
        sets = [int(str(row[f"side{x}_sets_won"]).strip()) for x in (1, 2)]
    except (TypeError, KeyError, ValueError):
        return None
    if sorted(sets) not in (([0, 2], [1, 2]) if TOUR == "wta" else ([0, 2], [1, 2], [0, 3], [1, 3], [2, 3])):
        return None
    played = sum(sets)
    parsed = []
    for i in range(1, 6):
        val = [str(row.get(f"set{i}_side{x}") or "").strip() for x in (1, 2)]
        if all(not v for v in val):
            if i <= played:
                return None
            continue
        if i > played or any(not REGULAR_SET.fullmatch(v) for v in val):
            return None
        games = tuple(int(REGULAR_SET.fullmatch(v)[1]) for v in val)
        if games[0] == games[1]:
            return None
        high, low = max(games), min(games)
        if not ((high == 6 and low <= 4) or (high == 7 and low in (5, 6))):
            return None
        parsed.append(games)
    if len(parsed) != played or [sum(a > b for a, b in parsed), sum(b > a for a, b in parsed)] != sets:
        return None
    return {"sets": sets, "games": [sum(x[i] for x in parsed) for i in range(2)],
            "first": int(parsed[0][0] > parsed[0][1]),
            "second": int(parsed[1][0] > parsed[1][1])}


def canonical_year(frame):
    needed = {"match_id", "tour", "scheduled_at", "player1_id", "player1_name",
              "player2_id", "player2_name", "winner_id", "tournament", "status", "stats_json"}
    if not needed.issubset(frame.columns):
        raise ValueError("Canonical schema missing required identity/stat fields")
    if frame.match_id.astype(str).duplicated().any():
        raise ValueError("Duplicate canonical IDs")
    pairs = defaultdict(list)
    ids = defaultdict(list)
    for _, r in frame.iterrows():
        if str(r["tour"]).lower() != TOUR:
            continue
        day = pd.Timestamp(r["scheduled_at"]).date()
        if day.year != YEAR:
            raise ValueError("Unexpected canonical WTA year")
        left, right = full_name(r["player1_name"]), full_name(r["player2_name"])
        if left and right and left != right:
            pairs[frozenset((left, right))].append((day, r))
        a, b = str(r["player1_id"]), str(r["player2_id"])
        if a and b and a != b:
            ids[frozenset((a, b))].append((day, r))
    return pairs, ids


def _matching_rows(candidates, row, side, score, *, direct):
    try:
        source_day = date.fromisoformat(str(row["date"]))
    except (KeyError, ValueError):
        return []
    result = []
    for day, target in candidates:
        if abs((day-source_day).days) > 1:
            continue
        if norm(target["status"]) not in ("completed", "finished"):
            continue
        if tournament_score(row.get("tournament"), target["tournament"])[0] <= 0:
            continue
        canonical_winner = str(target["winner_id"])
        expected = str(target["player1_id"] if (side == 1) == direct else target["player2_id"])
        if not canonical_winner or canonical_winner != expected:
            continue
        # Source score already established winner. No match merely on name/day.
        if score["sets"][side-1] != max(score["sets"]):
            continue
        result.append(target)
    return list({str(r["match_id"]): r for r in result}.values())


def _stats(score, direct):
    if direct:
        sets, games, fst, snd = score["sets"], score["games"], score["first"], score["second"]
    else:
        sets, games, fst, snd = score["sets"][::-1], score["games"][::-1], 1-score["first"], 1-score["second"]
    return {"total_sets": sum(sets), "total_games": sum(games),
            "deciding_set": int(sum(sets) == 3),
            "p1_first_set_won": fst, "p2_first_set_won": 1-fst,
            "p1_second_set_won": snd, "p2_second_set_won": 1-snd,
            "p1_games_won": games[0], "p2_games_won": games[1],
            "p1_sets_won": sets[0], "p2_sets_won": sets[1]}


def classify(rows, details, frame, cdb_sha):
    pairs, ids = canonical_year(frame)
    detail_index = defaultdict(list)
    for obj in details:
        if not isinstance(obj, dict) or obj.get("source") != "TennisExplorer":
            continue
        key = str(obj.get("match_id") or "")
        if not key.isdigit():
            continue
        detail_index[key].append(obj)
    counts = Counter()
    claims = defaultdict(list)
    player_votes = defaultdict(set)
    source_ids = set()
    anchors = {}
    for row in rows:
        sid = str(row.get("match_id") or "")
        if (not sid or sid in source_ids or row.get("category") != f"{TOUR}-single"):
            raise ValueError("Duplicate/missing/wrong source match")
        source_ids.add(sid)
        slugs, score = result_slugs(row), score_values(row)
        if not slugs or not score:
            counts["invalid_result_or_slug"] += 1
            continue
        if len(detail_index[sid]) != 1:
            counts["no_unique_detail"] += 1
            continue
        d = detail_index[sid][0]
        players = d.get("players")
        if not isinstance(players, list) or len(players) != 2:
            counts["invalid_detail_names"] += 1
            continue
        dn = [full_name(p.get("name")) if isinstance(p, dict) else None for p in players]
        ds = [player_slug(p.get("profile_url")) if isinstance(p, dict) else None for p in players]
        if not all(dn) or tuple(ds) != slugs or dn[0] == dn[1]:
            counts["detail_identity_incomplete"] += 1
            continue
        candidate = pairs.get(frozenset(dn), ())
        matches = []
        for day, can in candidate:
            n1, n2 = full_name(can["player1_name"]), full_name(can["player2_name"])
            direct = dn == [n1, n2]
            swapped = dn == [n2, n1]
            if direct == swapped:
                continue
            matches.extend((can, direct) for c in _matching_rows([(day, can)], row, result_side(row), score, direct=direct))
        if len(matches) != 1:
            counts["anchor_ambiguous_or_unmatched"] += 1
            continue
        can, direct = matches[0]
        anchors[sid] = (str(can["match_id"]), direct)
        for pos, slug in enumerate(slugs):
            player_votes[slug].add(str(can["player1_id"] if ((pos == 0) == direct) else can["player2_id"]))
        counts["exact_fullname_anchors"] += 1

    votes_reverse = defaultdict(set)
    for slug, choices in player_votes.items():
        for chosen in choices:
            votes_reverse[chosen].add(slug)
    crosswalk = {slug: next(iter(choices)) for slug, choices in player_votes.items()
                 if len(choices) == 1 and len(votes_reverse[next(iter(choices))]) == 1}
    counts["unique_crosswalk_slugs"] = len(crosswalk)

    for row in rows:
        sid = str(row["match_id"])
        slugs, score = result_slugs(row), score_values(row)
        if not slugs or not score:
            continue
        if any(s not in crosswalk for s in slugs):
            continue
        a, b = (crosswalk[s] for s in slugs)
        if a == b:
            continue
        matches = []
        for day, can in ids.get(frozenset((a, b)), ()):
            direct = str(can["player1_id"]) == a and str(can["player2_id"]) == b
            swapped = str(can["player1_id"]) == b and str(can["player2_id"]) == a
            if direct == swapped:
                continue
            matches.extend((can, direct) for c in _matching_rows([(day, can)], row, result_side(row), score, direct=direct))
        if len(matches) != 1:
            counts["crosswalk_event_unmatched_or_ambiguous"] += 1
            continue
        can, direct = matches[0]
        if sid in anchors and anchors[sid] != (str(can["match_id"]), direct):
            raise ValueError("Anchor/crosswalk contradiction")
        claims[str(can["match_id"])].append((sid, row, can, direct, score))
        counts["source_player_id_links"] += 1

    stage, quarantine = [], []
    for mid, proposals in claims.items():
        if len(proposals) != 1:
            counts["competing_source_matches"] += 1
            quarantine.extend({"source_match_id": s, "match_id": mid, "reason": "competing_source_claim"}
                              for s, *_ in proposals)
            continue
        sid, row, can, direct, score = proposals[0]
        proposed = _stats(score, direct)
        if set(proposed) != FIELD_NAMES:
            raise ValueError("Unexpected score key")
        original = json.loads(can["stats_json"])
        if not isinstance(original, dict):
            raise ValueError("Malformed existing stats JSON")
        missing = {}
        conflicts = []
        for key, val in proposed.items():
            v = original.get(key)
            if v is None:
                missing[key] = val
            else:
                try:
                    same = (not isinstance(v, bool) and isinstance(v, (int, float))
                            and float(v) == float(val))
                except (TypeError, ValueError):
                    same = False
                if not same:
                    conflicts.append(key)
                else:
                    counts["already_present_equal_fields"] += 1
        if conflicts:
            counts["matches_quarantined_existing_score_conflict"] += 1
            counts["missing_fields_blocked_by_conflict"] += len(missing)
            quarantine.append({"source_match_id": sid, "match_id": mid,
                               "reason": "existing_score_conflict", "fields": sorted(conflicts)})
            continue
        if not missing:
            counts["fully_existing_score_matches"] += 1
            continue
        stage.append({
            "schema": 1, "source": f"tennisexplorer_{TOUR}{YEAR}_complete_match_results",
            "source_id": sid, "match_id": mid, "year": YEAR,
            "source_sha256": SOURCE_SHA, "cdb_sha256": cdb_sha,
            "expected_identity": {k: str(can[k]) for k in (
                "match_id", "tour", "scheduled_at", "player1_id", "player2_id",
                "player1_name", "player2_name", "winner_id", "tournament", "status")},
            "source_player_slugs": list(slugs) if (slugs := result_slugs(row)) else [],
            "source_player_anchor_status": "two_unique_fullname_attested_player_slugs",
            "expected_original_null_fields": sorted(missing),
            "additions": missing, "model_eligibility": "historical_postmatch_only",
            "available_at": None,
        })
        counts["staged_matches"] += 1
        counts["staged_fields"] += len(missing)
    counts["source_rows"] = len(rows)
    counts["details_rows"] = len(details)
    counts["quarantined_source_claims"] = len(quarantine)
    return stage, quarantine, dict(sorted(counts.items()))


def main():
    p = argparse.ArgumentParser()
    for key in ("source", "history", "manifest", "release", "out"):
        p.add_argument("--" + key, required=True, type=Path)
    args = p.parse_args()
    rows, details = load_archive(args.source)
    cdb_sha = sha256(args.history)
    release = json.loads(args.release.read_text())
    digests = {x["name"]: x.get("digest") for x in release["assets"]}
    if digests.get(args.history.name) != "sha256:" + cdb_sha:
        raise ValueError("Release year digest does not match history")
    if digests.get(args.manifest.name) != "sha256:" + sha256(args.manifest):
        raise ValueError("Release manifest digest mismatch")
    meta = json.loads(args.manifest.read_text())["years"][str(YEAR)]
    if meta.get("sha256") != cdb_sha or int(meta.get("rows", -1)) < 1000:
        raise ValueError("Year manifest mismatch")
    frame = pd.read_parquet(args.history)
    if len(frame) != int(meta["rows"]):
        raise ValueError("Canonical year row count drift")
    stage, quarantined, counts = classify(rows, details, frame, cdb_sha)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    for name, records in (("stage.jsonl", stage), ("quarantine.jsonl", quarantined)):
        (out / name).write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in records))
    report = {"schema": 1, "status": "read_only_score_delta",
              "source_sha256": SOURCE_SHA, "cdb_sha256": cdb_sha, "year": YEAR,
              "stage_sha256": sha256(out / "stage.jsonl"),
              "counts": counts, "production_mutated": False,
              "model_trained": False, "model_promoted": False, "provider_api_requests": 0,
              "score_feature_policy": "past_completed_matches_only; not same-match pre-match inputs"}
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
