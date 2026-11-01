#!/usr/bin/env python3
"""Strict, repeatable MoviOdds finished stats -> existing CDB importer stage.

Read-only: NEVER imports, writes canonical history, modifies a model or
synthesizes source identities. Existing CDB importer is the only writer.
Input must be a SHA-verified MoviOdds CDB JSON archive v2.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

from moviodds_cdb_format import verify_cdb_archive


def _norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def _when(value: object) -> datetime:
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Missing timezone")
    return d.astimezone(timezone.utc)


def _normal_surface(value: object) -> str:
    s = _norm(value)
    for name in ("hard", "clay", "grass", "carpet"):
        if name in s.split():
            return name
    return ""


def _source_event(match: dict) -> tuple[str, str] | None:
    league = _norm(match["league"])
    hint = match["tour_hint"]
    if not hint or not league.startswith(hint + " "):
        return None
    event = league[len(hint) + 1:].strip()
    if not event or len(event) < 3:
        return None
    return hint, event


def _event_match(event: str, canonical: str) -> bool:
    # Exact normalized event name or contiguous full source event phrase
    # (Paris inside Rolex Paris Masters). No token guesses or city aliases.
    c = _norm(canonical)
    return bool(c) and (c == event or (" " + event + " ") in (" " + c + " "))


def _result_score(candidate: dict) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Verify every set in final_score against source home/away set vectors.

    Never accept TB super-sets, partial sets, walkovers or retired fixtures as
    normal completed matches for automatic canonical enrichment.
    """
    match = candidate["match"]
    values = str(match["final_score_source"]).split(",")
    if not 2 <= len(values) <= 5:
        raise ValueError("Missing complete best-of-three/five score")
    sets = []
    for value in values:
        m = re.fullmatch(r"\s*(\d{1,2})-(\d{1,2})\s*", value)
        if m is None:
            raise ValueError("Unsupported or incomplete set score")
        a, b = int(m.group(1)), int(m.group(2))
        if not ((a == 6 and b <= 4) or (b == 6 and a <= 4)
                or (a == 7 and b in (5, 6))
                or (b == 7 and a in (5, 6))):
            raise ValueError("Partial/invalid set or unsupported tie-break")
        sets.append((a, b))
    if len(sets) not in (2, 3, 4, 5):
        raise ValueError("Invalid number of sets")
    format_source = str(match["best_of_source"] or "")
    best = 5 if "5" in format_source else 3 if "3" in format_source else None
    if best is None:
        raise ValueError("Unknown source match format")
    needed = best // 2 + 1
    wins_a = sum(a > b for a, b in sets)
    wins_b = sum(b > a for a, b in sets)
    if (max(wins_a, wins_b) != needed
            or min(wins_a, wins_b) >= needed
            or wins_a + wins_b != len(sets)
            or len(sets) > best):
        raise ValueError("Incomplete or impossible match score")
    # Original set vectors are only evidence when explicitly captured.
    payload = candidate.get("_raw") or {}
    stats = payload.get("stats") or {}
    home, away = stats.get("home") or {}, stats.get("away") or {}
    raw_h, raw_a = home.get("sets"), away.get("sets")
    if (not isinstance(raw_h, list) or not isinstance(raw_a, list)
            or len(raw_h) != len(sets) or len(raw_a) != len(sets)
            or any(isinstance(v, bool) or not isinstance(v, int)
                   for v in raw_h + raw_a)):
        raise ValueError("Source score side vectors unavailable")
    if tuple(raw_h) != tuple(v[0] for v in sets) or tuple(raw_a) != tuple(v[1] for v in sets):
        raise ValueError("Source final score and side vectors disagree")
    return ("home" if wins_a > wins_b else "away"), tuple(sets)


def _signature(match) -> dict:
    # Exact existing import_offline_linked_serve_return.py signature. Revalidate
    # dynamically at import, and always compare with live CDB before writing.
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id), "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id), "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _matching_candidates(c: dict, canonical_index: dict) -> list:
    match = c["match"]
    source_event = _source_event(match)
    if source_event is None:
        return []
    tour, event = source_event
    names = frozenset((_norm(match["home_name"]), _norm(match["away_name"])))
    if len(names) != 2 or any(len(x) < 4 for x in names):
        return []
    finished = _when(match["finished_at_utc"])
    # The fixture kickoff field is absent from many historical results.
    # Strictly bound candidate dates to completion date and previous UTC day.
    result = []
    for delta in (0, 1):
        day = finished.date() - timedelta(days=delta)
        for obj in canonical_index.get((tour, day, names), ()):
            if not obj.is_completed:
                continue
            kickoff = obj.scheduled_at.astimezone(timezone.utc)
            age = (finished - kickoff).total_seconds()
            if not 0 <= age <= 48 * 3600:
                continue
            if not _event_match(event, obj.tournament):
                continue
            surface = _normal_surface(match["surface_source"])
            canonical_surface = _normal_surface(obj.surface)
            if not surface or not canonical_surface or surface != canonical_surface:
                continue
            source_best = 5 if "5" in str(match["best_of_source"]) else 3
            if obj.best_of is not None and int(obj.best_of) != source_best:
                continue
            # Source kickoff is a high-quality optional corroborator only.
            source_kickoff = match.get("scheduled_at_utc")
            if source_kickoff and abs((_when(source_kickoff) - kickoff).total_seconds()) > 3600:
                continue
            result.append(obj)
    return result


def link_archive(data: dict, matches: list, *, archive_sha256: str) -> tuple[list[dict], list[dict], dict]:
    """Return exact-schema potential import rows, rejected review and QA.

    Strict 1:1 match identity; no alias collisions, no player-side guesses.
    CDB preexisting non-NULL statistic conflicts quarantine the entire row.
    """
    verify_cdb_archive(data)
    if not re.fullmatch(r"[a-f0-9]{64}", archive_sha256):
        raise ValueError("Invalid immutable archive checksum")
    index = defaultdict(list)
    for m in matches:
        pair = frozenset((_norm(m.player1_name), _norm(m.player2_name)))
        index[(str(m.tour).lower(), m.scheduled_at.astimezone(timezone.utc).date(), pair)].append(m)

    proposed = []
    review = []
    tally = Counter()
    for r in data["records"]:
        tally["raw"] += 1
        c = dict(r["cdb_candidate"])
        c["_raw"] = r["payload"]
        identity = c["source_fixture_id"]
        if c["match"]["event_type"] != "singles_unconfirmed":
            reason = "doubles"
        elif c["match"]["tour_hint"] not in ("atp", "wta"):
            reason = "tour_unverified"
        else:
            try:
                source_winner, score = _result_score(c)
            except (TypeError, ValueError, KeyError) as exc:
                reason = "source_set_score_not_verified"
            else:
                candidates = _matching_candidates(c, index)
                if len(candidates) != 1:
                    reason = "unmatched" if not candidates else "ambiguous_identity"
                else:
                    m = candidates[0]
                    h, a = _norm(c["match"]["home_name"]), _norm(c["match"]["away_name"])
                    p1, p2 = _norm(m.player1_name), _norm(m.player2_name)
                    orient = ((h == p1 and a == p2) or (h == p2 and a == p1))
                    source_winner_id = m.player1_id if (source_winner == "home") == (h == p1) else m.player2_id
                    if not orient:
                        reason = "orientation_unverified"
                    elif str(m.winner_id or "") != str(source_winner_id):
                        reason = "winner_conflict"
                    else:
                        home_c, away_c = c["source_side_counts"]["home"], c["source_side_counts"]["away"]
                        values = {}
                        for src, stats in (("home", home_c), ("away", away_c)):
                            prefix = ("p1" if (src == "home") == (h == p1) else "p2")
                            for key in ("aces", "double_faults"):
                                value = stats.get(key)
                                if value is not None:
                                    values[f"{prefix}_{key}"] = float(value)
                        old = m.stats or {}
                        conflicts = [key for key, value in values.items()
                                     if old.get(key) is not None
                                     and (not isinstance(old[key], (int, float))
                                          or not math.isfinite(old[key])
                                          or abs(float(old[key]) - value) > 1e-6)]
                        if conflicts:
                            reason = "cdb_stat_conflict"
                        else:
                            added = {key: value for key, value in values.items()
                                     if old.get(key) is None}
                            if not added:
                                reason = "already_present_or_no_usable_values"
                            else:
                                proposed.append({
                                    "schema": 1, "import_ready": True,
                                    "match_id": str(m.match_id),
                                    "canonical": _signature(m),
                                    # Include all observed values so dry-run
                                    # detects conflicts introduced after stage.
                                    "incoming_stats": added,
                                    "baseline_stats": dict(old),
                                    "provenance": [{
                                        "source": "moviodds",
                                        "source_fixture_id": identity,
                                        "source_sha256": r["sha256"],
                                        "archive_sha256": archive_sha256,
                                        "source_updated_at_utc": c["provenance"]["source_updated_at_utc"],
                                        "source_finalized_at_utc": c["provenance"]["source_finalized_at_utc"],
                                        "evidence": [
                                            "full_names_exact",
                                            "tournament_source_phrase_exact",
                                            "date_bounded_48h",
                                            "surface_exact", "unique_canonical_match",
                                            "source_full_set_vectors_validated",
                                            "canonical_winner_independently_agrees",
                                            "no_cdb_stat_conflicts",
                                        ],
                                        "score_source": c["match"]["final_score_source"],
                                        "source_orientation": {
                                            "home": "p1" if h == p1 else "p2",
                                            "away": "p2" if h == p1 else "p1",
                                        },
                                        "score_independently_reproduced": False,
                                    }],
                                })
                                tally["linked_candidate"] += 1
                                tally["new_values_candidates"] += len(added)
                                continue
        tally[reason] += 1
        review.append({
            "source": "moviodds", "source_fixture_id": identity,
            "reason": reason, "source_sha256": r["sha256"],
            "archive_sha256": archive_sha256,
            "home": c["match"]["home_name"], "away": c["match"]["away_name"],
            "league": c["match"]["league"],
        })

    # Distinct external IDs pointing to the same canonical ID are never both
    # allowed, even if their source values match.
    mid_counts = Counter(x["match_id"] for x in proposed)
    duplicate_ids = {mid for mid, count in mid_counts.items() if count > 1}
    if duplicate_ids:
        keep = []
        for row in proposed:
            if row["match_id"] in duplicate_ids:
                tally["ambiguous_identity"] += 1
                review.append({
                    "source": "moviodds", "source_fixture_id":
                    row["provenance"][0]["source_fixture_id"],
                    "reason": "duplicate_canonical_id", "match_id": row["match_id"],
                })
            else:
                keep.append(row)
        proposed = keep

    proposed.sort(key=lambda row: row["match_id"])
    review.sort(key=lambda row: row["source_fixture_id"])
    report = {
        "schema": 1, "source": "moviodds", "state": "READ_ONLY_CDB_STAGE",
        "source_archive_sha256": archive_sha256, "raw": tally["raw"],
        "linked": len(proposed), "net_new": 0,
        "enriched_candidates": len(proposed),
        "new_values_candidates": sum(
            sum(value is not None and row["baseline_stats"].get(key) is None
                for key, value in row["incoming_stats"].items())
            for row in proposed
        ),
        "rejected": len(review), "counts": dict(tally),
        "actual_cdb_values_written": 0, "production_mutated": False,
        "score_independently_reproduced": False,
    }
    if report["raw"] != len(proposed) + len(review):
        raise ValueError("MoviOdds stage lost a source row")
    return proposed, review, report


def stage(archive: Path, history: Path, output: Path) -> dict:
    # Do NOT import or modify canonical history. Only read snapshots that were
    # already independently verified against the private CDB release hashes.
    from tbt.data.history_snapshot import load_snapshot
    original = archive.read_bytes()
    source_sha = hashlib.sha256(original).hexdigest()
    data = json.loads(original)
    verify_cdb_archive(data)
    match_day = datetime.fromisoformat(data["days"][0]).date()
    years = {match_day.year, (match_day - timedelta(days=1)).year}
    matches = []
    for year in sorted(years):
        file = history / f"history-{year}.parquet"
        if file.is_file():
            matches.extend(load_snapshot(file))
        elif year == match_day.year:
            raise FileNotFoundError("Required CDB yearly history partition missing")
    ready, review, report = link_archive(data, matches, archive_sha256=source_sha)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("eligible.jsonl", ready), ("review.jsonl", review)):
        (output / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                    for row in rows), encoding="utf-8",
        )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    from _bootstrap import ROOT  # noqa: F401
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.archive, args.history_dir, args.out_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
