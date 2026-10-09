"""Read-only CDB player-identity crosswalk preflight, fail closed.

Evidence comes from checksum-verified CDB event rows, not names or ranking
alone. No source edits, model promotion, provider requests, or release writes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unicodedata
import re
import pandas as pd

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
DIRECTORY = Path("/tmp/blinq-comparator-readonly-audit/comparator-players.json")
YEARS = tuple(range(2017, 2027))
FIELDS = ("match_id", "tour", "scheduled_at", "player1_id", "player1_name",
          "player2_id", "player2_name", "winner_id", "tournament", "round_name",
          "surface")
OUTPUT = Path("/tmp/blinq-identity-crosswalk-dryrun.json")


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def abbreviation(name):
    parts = norm(name).split()
    if len(parts) != 2:
        return None
    if len(parts[0]) == 1 and len(parts[1]) > 1:
        return parts[0], parts[1]
    if len(parts[1]) == 1 and len(parts[0]) > 1:
        return parts[1], parts[0]
    return None


def full_initial(name):
    tokens = norm(name).split()
    if len(tokens) < 2 or len(tokens[0]) < 2 or len(tokens[-1]) < 2:
        return None
    return tokens[0][0], tokens[-1]


def propose_candidates(directory):
    by_name = defaultdict(list)
    by_initial = defaultdict(list)
    for row in directory.get("players", []):
        tour = str(row.get("tour") or "").lower()
        pid = str(row.get("player_id") or "")
        if tour not in {"atp", "wta"} or not pid:
            continue
        name = norm(row.get("name"))
        if name:
            by_name[(tour, name)].append(row)
        initial = full_initial(row.get("name"))
        if initial:
            by_initial[(tour, initial)].append(row)

    proposed = {}
    quarantine = Counter()
    for (tour, full_name), rows in by_name.items():
        provider = [r for r in rows if not str(r["player_id"]).startswith("hist-js:")]
        historical = [r for r in rows if str(r["player_id"]).startswith("hist-js:")]
        if len(provider) != 1:
            if historical or len(provider) > 1:
                quarantine["nonunique_full_name_owner"] += 1
            continue
        for old in historical:
            proposed[(tour, str(old["player_id"]))] = (str(provider[0]["player_id"]), full_name, "full_name")

    for (tour, _name), rows in by_name.items():
        for short in rows:
            if not str(short.get("player_id") or "").startswith("hist-js:"):
                continue
            initial = abbreviation(short.get("name"))
            if not initial:
                continue
            candidates = by_initial.get((tour, initial), [])
            possible_names = {norm(p.get("name")) for p in candidates}
            provider = [p for p in candidates if not str(p["player_id"]).startswith("hist-js:")]
            if len(provider) != 1 or len(possible_names) != 1:
                quarantine["ambiguous_initial_surname"] += 1
                continue
            key = (tour, str(short["player_id"]))
            destination = str(provider[0]["player_id"])
            prior = proposed.get(key)
            if prior and prior[0] != destination:
                quarantine["contradicting_target"] += 1
                proposed.pop(key, None)
            elif not prior:
                proposed[key] = (destination, norm(provider[0]["name"]), "abbrev_needs_event_proof")
    return proposed, quarantine


def match_token(row, participant):
    left = str(row.get("player1_id") or "")
    right = str(row.get("player2_id") or "")
    if participant not in (left, right) or left == right:
        return None
    opponent = right if participant == left else left
    opp_name = row.get("player2_name") if participant == left else row.get("player1_name")
    winner = str(row.get("winner_id") or "")
    if winner not in {left, right}:
        return None
    day = str(row.get("scheduled_at"))[:10]
    if len(day) != 10:
        return None
    return {
        "match_id": str(row.get("match_id") or ""),
        "date": day,
        "opponent": norm(opp_name),
        "opponent_id": opponent,
        "tournament": norm(row.get("tournament")),
        "round": norm(row.get("round_name")),
        "surface": norm(row.get("surface")),
        "won": winner == participant,
    }


def compare_events(old, current):
    # The exact UTC calendar date, normalized opposing player's name, and
    # tournament must agree. Never guess nearby dates or similarly ranked IDs.
    if (old["date"], old["opponent"]) != (current["date"], current["opponent"]):
        return "unrelated"
    if not old["opponent"] or not old["tournament"] or not current["tournament"]:
        return "conflict"
    for field in ("tournament", "surface", "round", "won"):
        if field == "round" and (not old[field] or not current[field]):
            continue
        if old[field] != current[field]:
            return "conflict"
    if old["match_id"] == current["match_id"]:
        return "conflict"
    return "exact"


def evaluate_pair(old_events, current_events):
    by_day_opp = defaultdict(list)
    for row in current_events:
        by_day_opp[(row["date"], row["opponent"])].append(row)
    exact = []
    conflicts = []
    duplicate_claim = False
    claimed_matches = set()
    for old in old_events:
        matches = by_day_opp.get((old["date"], old["opponent"]), [])
        if not matches:
            continue
        results = [(candidate, compare_events(old, candidate)) for candidate in matches]
        if len(results) != 1 or results[0][1] != "exact":
            conflicts.append({"old": old["match_id"], "current": [c["match_id"] for c in matches]})
            continue
        current = results[0][0]
        if current["match_id"] in claimed_matches:
            duplicate_claim = True
        claimed_matches.add(current["match_id"])
        exact.append((old["match_id"], current["match_id"]))
    if duplicate_claim:
        conflicts.append({"reason": "many_to_one_event"})
    return {
        "source_matches": len(old_events),
        "target_matches": len(current_events),
        "overlap": len(exact),
        "conflict": len(conflicts),
        "duplicate_event_pairs": exact,
        "conflict_examples": conflicts[:3],
        "eligible": len(exact) >= 2 and not conflicts,
    }


def release_download(name, folder):
    cmd = ["gh", "release", "download", TAG, "--repo", REPO, "--pattern",
           name, "--dir", str(folder), "--clobber"]
    subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=150)
    path = folder / name
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError("Missing or empty release asset: " + name)
    return path


def audit_from_release(directory):
    raw = directory.read_bytes()
    snapshot = json.loads(raw)
    proposals, rejected = propose_candidates(snapshot)
    wanted = set(proposals) | {(tour, to) for (tour, _), (to, _, _) in proposals.items()}
    observations = defaultdict(list)
    id_names = defaultdict(set)
    partition_meta = {}
    with tempfile.TemporaryDirectory(prefix="blinq-identity-cdb-audit-") as tmp:
        folder = Path(tmp)
        bundle = json.loads(release_download("_tbt_bundle_manifest.json", folder).read_text())
        manifest_path = release_download("history_manifest.json", folder)
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(bundle.get("files"), dict) or not isinstance(manifest.get("years"), dict):
            raise RuntimeError("Incomplete verified release inventory")
        for year in YEARS:
            entry = manifest["years"].get(str(year))
            if not isinstance(entry, dict):
                raise RuntimeError("Missing CDB partition " + str(year))
            name = str(entry.get("asset") or f"history-{year}.parquet")
            meta = bundle["files"].get(name)
            expected = meta.get("sha256") if isinstance(meta, dict) else None
            if not expected or len(expected) != 64:
                raise RuntimeError("Missing CDB checksum " + name)
            local = release_download(name, folder)
            actual = sha256(local.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError("CDB hash mismatch " + name)
            frame = pd.read_parquet(local, columns=list(FIELDS))
            partition_meta[str(year)] = {"sha256": actual, "rows": len(frame)}
            for record in frame.itertuples(index=False, name=None):
                row = dict(zip(FIELDS, record))
                tour = str(row["tour"] or "").lower()
                if tour not in {"atp", "wta"}:
                    continue
                for participant, name in ((row["player1_id"], row["player1_name"]),
                                          (row["player2_id"], row["player2_name"])):
                    key = (tour, str(participant or ""))
                    if key not in wanted:
                        continue
                    token = match_token(row, key[1])
                    if token is not None:
                        observations[key].append(token)
                        id_names[key].add(norm(name))
            local.unlink()
    approved = []
    counts = Counter()
    review = []
    for (tour, source), (target, spelling, evidence) in sorted(proposals.items()):
        result = evaluate_pair(observations.get((tour, source), []),
                               observations.get((tour, target), []))
        source_names = id_names.get((tour, source), set())
        target_names = id_names.get((tour, target), set())
        compatible = bool(source_names and target_names)
        # The name in canonical history may be abbreviated; never force
        # a mapping to a differently named person on the same initial.
        if evidence == "full_name":
            compatible = compatible and spelling in source_names and spelling in target_names
        if not compatible:
            counts["source_name_conflict_or_missing"] += 1
        elif result["conflict"]:
            counts["overlap_conflict"] += 1
        elif not result["eligible"]:
            counts["insufficient_independent_overlap"] += 1
        else:
            counts["verified_links"] += 1
            approved.append({
                "tour": tour, "from_id": source, "to_id": target,
                "name": spelling, "source_matches": result["source_matches"],
                "target_matches": result["target_matches"],
                "proven_event_overlaps": result["overlap"],
                "excluded_overlap_pairs": result["duplicate_event_pairs"],
                "evidence": "independent_identical_cdb_events_2plus",
            })
        if len(review) < 30 and not (result["eligible"] and compatible):
            review.append({"tour": tour, "source": source, "target": target,
                           "reason": "no_evidence" if not result["overlap"] else "collision_or_name",
                           "source_matches": result["source_matches"],
                           "target_matches": result["target_matches"],
                           "overlaps": result["overlap"],
                           "conflicts": result["conflict"]})
    counts["proposed_candidate_links"] = len(proposals)
    counts["accepted_not_imported"] = len(approved)
    counts["input_snapshot_players"] = len(snapshot.get("players") or [])
    counts["queried_cdb_partitions"] = len(partition_meta)
    report = {
        "schema": 1, "state": "dry_run_only",
        "model_unchanged": True, "cdb_mutated": False,
        "release": TAG, "comparator_directory_sha256": sha256(raw).hexdigest(),
        "release_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest() if False else None,
        "period": [min(YEARS), max(YEARS)],
        "counts": dict(counts), "candidate_reasons": dict(rejected),
        "partitions": partition_meta,
        "verified_links": approved, "quarantine_examples": review,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    print("CDB_IDENTITY_RECONCILIATION " + json.dumps({
        "status": report["state"], "counts": report["counts"],
        "source_hash": report["comparator_directory_sha256"],
        "approved_sample": approved[:18], "review_sample": review[:12],
    }, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    if not DIRECTORY.is_file():
        raise SystemExit("Verified comparator directory missing")
    audit_from_release(DIRECTORY)
