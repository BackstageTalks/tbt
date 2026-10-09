"""Read-only identity linking: TennisExplorer staged singles -> authoritative CDB.

No CDB partitions are written. A link requires unique match identity evidence:
tour, player pair, winner, tournament, day (±1), and consistent surface.
Ranking source-ID crosswalks are proposed only from non-conflicting match links.
"""
from __future__ import annotations

import argparse
import csv
import json
import unicodedata
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_odds import tournament_score


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def stage_rows(root, years):
    for category in ("atp-single", "wta-single"):
        for year in years:
            path = root / "matches" / category / f"{year}.jsonl"
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                        match = obj.get("match_record") if isinstance(obj, dict) else None
                    except ValueError:
                        raise ValueError(f"Malformed staged JSON: {path}:{line_no}")
                    if isinstance(match, dict):
                        yield obj


def source_date(row):
    try:
        return datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00")).date()
    except (TypeError, ValueError, KeyError):
        return None


def event_winner_side(record):
    win = str(record.get("winner_id") or "")
    if win and win == str(record.get("player1_id") or ""):
        return 1
    if win and win == str(record.get("player2_id") or ""):
        return 2
    return None


def canonical_winner_side(match):
    winner = str(match.winner_id or "")
    if winner and winner == str(match.player1_id):
        return 1
    if winner and winner == str(match.player2_id):
        return 2
    return None


def align(record, match):
    a, b = norm(record.get("player1_name")), norm(record.get("player2_name"))
    x, y = norm(match.player1_name), norm(match.player2_name)
    if not a or not b or a == b:
        return None
    if a == x and b == y:
        return "direct"
    if a == y and b == x:
        return "swapped"
    return None


def match_link(record, canonical):
    orientation = align(record, canonical)
    if orientation is None:
        return None
    if str(record.get("tour") or "").lower() != str(canonical.tour or "").lower():
        return None
    date = source_date(record)
    if date is None:
        return None
    delta = (canonical.scheduled_at.date() - date).days
    if abs(delta) > 1:
        return None
    source_win = event_winner_side(record)
    canon_win = canonical_winner_side(canonical)
    # We only accept fully corroborated concluded matches.
    if not source_win or not canon_win:
        return None
    oriented_winner = source_win if orientation == "direct" else 3 - source_win
    if oriented_winner != canon_win:
        return None
    source_surface = str(record.get("surface") or "").strip().lower()
    canonical_surface = str(canonical.surface or "").strip().lower()
    if source_surface not in ("", "unknown") and canonical_surface not in ("", "unknown"):
        if source_surface != canonical_surface:
            return None
    source_tournament = str(record.get("tournament") or "")
    target_tournament = str(canonical.tournament or "")
    score, evidence = tournament_score(source_tournament, target_tournament)
    if score <= 0:
        return None
    source_round = str(record.get("round_name") or "").strip().lower()
    canon_round = str(canonical.round_name or "").strip().lower()
    if source_round and canon_round and source_round != canon_round:
        return None
    return {
        "orientation": orientation,
        "date_delta_days": delta,
        "tournament_score": score,
        "tournament_evidence": evidence,
        "surface_agrees_or_unknown": True,
        "round_agrees_or_unknown": True,
        "matching_points": (2 if delta == 0 else 0) + score + (1 if source_round else 0),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True, help="Current CDB history partitions + manifest")
    ap.add_argument("--staging-root", required=True, help="tbt-data/.../cdb_staging")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--from-year", type=int, default=1998)
    ap.add_argument("--to-year", type=int, default=2026)
    args = ap.parse_args()
    if args.from_year > args.to_year:
        ap.error("Invalid range")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    history, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity integrity check failed")

    by_pair = defaultdict(list)
    for match in history:
        key = (str(match.tour or "").lower(), frozenset((norm(match.player1_name), norm(match.player2_name))))
        by_pair[key].append(match)

    counts = Counter()
    proposed = []
    review = []
    for obj in stage_rows(Path(args.staging_root), range(args.from_year, args.to_year + 1)):
        counts["source_singles"] += 1
        record = obj["match_record"]
        if obj.get("identity_status") != "source_scoped_unlinked":
            review.append({"source_match_id": obj.get("source_match_id"), "reason":"unexpected_trust_state"})
            counts["invalid_state"] += 1
            continue
        key = (str(record.get("tour") or "").lower(),
               frozenset((norm(record.get("player1_name")), norm(record.get("player2_name")))))
        matches = []
        for candidate in by_pair.get(key, []):
            evidence = match_link(record, candidate)
            if evidence is not None:
                matches.append((candidate, evidence))
        # Multiple matches are ambiguous regardless of score ranking.
        if len(matches) != 1:
            counts["unmatched" if not matches else "ambiguous"] += 1
            if matches:
                review.append({"source_match_id":obj.get("source_match_id"),
                               "reason":"ambiguous",
                               "candidate_canonical_ids":[m.match_id for m,_ in matches]})
            continue
        match, evidence = matches[0]
        proposal = {
            "source_match_id": obj["source_match_id"],
            "canonical_match_id": str(match.match_id),
            "tour": record["tour"],
            "source_date": str(source_date(record)),
            "source_player1_id": record["player1_id"],
            "source_player2_id": record["player2_id"],
            "canonical_player1_id": str(match.player1_id) if evidence["orientation"]=="direct" else str(match.player2_id),
            "canonical_player2_id": str(match.player2_id) if evidence["orientation"]=="direct" else str(match.player1_id),
            "evidence": evidence,
            "status": "linked_unique_identity_proposal",
            "production_mutated": False,
        }
        proposed.append(proposal)

    # Fail closed when multiple source matches point to one canonical event.
    by_canonical = defaultdict(list)
    for p in proposed:
        by_canonical[p["canonical_match_id"]].append(p)
    links = []
    for p in proposed:
        if len(by_canonical[p["canonical_match_id"]]) != 1:
            counts["duplicate_canonical_claims"] += 1
            review.append({"source_match_id":p["source_match_id"],
                           "reason":"duplicate_canonical_claim",
                           "canonical_match_id":p["canonical_match_id"]})
            continue
        links.append(p)
    player_votes = defaultdict(set)
    for link in links:
        for n in (1,2):
            key = (link["tour"],link[f"source_player{n}_id"])
            player_votes[key].add(link[f"canonical_player{n}_id"])

    with (out/"match_links.jsonl").open("w",encoding="utf-8") as f:
        for link in links:
            f.write(json.dumps(link,ensure_ascii=False)+"\n")
    with (out/"review.jsonl").open("w",encoding="utf-8") as f:
        for item in review:
            f.write(json.dumps(item,ensure_ascii=False)+"\n")
    player_path=out/"player_source_crosswalk.csv"
    with player_path.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=("tour","source_player_id","canonical_player_id","status"))
        writer.writeheader()
        for (tour,sid), ids in sorted(player_votes.items()):
            if len(ids)==1:
                writer.writerow({"tour":tour,"source_player_id":sid,
                                "canonical_player_id":next(iter(ids)),
                                "status":"single_unambiguous_identity_proposal"})
                counts["player_ids_unique"]+=1
            else:
                counts["player_ids_conflicted"]+=1
                review.append({"reason":"source_player_conflict","source_player_id":sid,
                               "candidate_canonical_ids":sorted(ids)})
    counts["linked_unique_matches"]=len(links)
    counts["production_writes"]=0
    report={"schema":1,"status":"PROPOSED_LINKS_ONLY_NOT_IMPORTED",
            "production_mutated":False,"counts":dict(counts),
            "policy":"No canonical write, no rank or odds feature promotion",
            "source_staging":str(args.staging_root),
            "canonical_history_dir":str(args.history_dir)}
    (out/"summary.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
