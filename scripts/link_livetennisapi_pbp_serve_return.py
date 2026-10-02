"""Audit/stage Live Tennis API academic point-by-point serve/return enrichment.

The source is the non-commercial academic dataset (CC BY-NC 4.0). Raw source
files are read only and are never copied into repository or tbt-data outputs.

Public sample schema:
  matches.csv(.gz)
  players.csv(.gz)
  points_sample_*.csv(.gz)

One point file row is a SCORE STATE. A point outcome is inferred only from an
unambiguous transition to the next score state for the same match. To avoid
turning partial observed tapes into fake full-match statistics, a match is
eligible only when:
  * the tape starts at an explicit 0-0 match state,
  * the tape ends at a terminal match state,
  * every non-duplicate transition has an unambiguous point winner,
  * the serving player is known for every inferred point,
  * both players have service and return denominators.

Canonical link policy is strict: exact UTC calendar date + exact normalized
player pair; exact surface/tournament/winner may only disambiguate candidates.
No fuzzy names or date windows.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_odds import norm_text
from tbt.models.feature_builder import FeatureBuilder


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _quality(stats: dict) -> bool:
    for side in ("p1", "p2"):
        serve, ret = FeatureBuilder._extract_quality(stats or {}, side)
        if serve is None or ret is None:
            return False
    return True


def _signature(match):
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.date().isoformat(),
        "player1_id": str(match.player1_id),
        "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id),
        "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""),
        "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""),
        "winner_id": str(match.winner_id or ""),
    }


def _parse_bool(value):
    text = str(value or "").strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _parse_int(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _parse_games(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out = []
    for item in data:
        try:
            number = int(item)
        except (TypeError, ValueError):
            return None
        if number < 0:
            return None
        out.append(number)
    return out


def _point_token(value):
    text = str(value or "").strip().upper()
    if text == "AD":
        text = "A"
    return text


def _state(row):
    return {
        "sets": (_parse_int(row.get("sets_p1")), _parse_int(row.get("sets_p2"))),
        "games": (_parse_games(row.get("games_p1")), _parse_games(row.get("games_p2"))),
        "points": (_point_token(row.get("points_p1")), _point_token(row.get("points_p2"))),
        "server": _parse_int(row.get("server")),
        "is_tiebreak": _parse_bool(row.get("is_tiebreak")),
    }


def _same_score(a, b):
    return (
        a["sets"] == b["sets"]
        and a["games"] == b["games"]
        and a["points"] == b["points"]
    )


def _point_winner(prev, nxt):
    """Infer winner (1/2) from one score-state transition; else None."""
    if _same_score(prev, nxt):
        return 0  # harmless duplicate state

    ps1, ps2 = prev["sets"]
    ns1, ns2 = nxt["sets"]
    if None in (ps1, ps2, ns1, ns2):
        return None
    ds = (ns1 - ps1, ns2 - ps2)
    if ds == (1, 0):
        return 1
    if ds == (0, 1):
        return 2
    if ds != (0, 0):
        return None

    pg1, pg2 = prev["games"]
    ng1, ng2 = nxt["games"]
    if pg1 is None or pg2 is None or ng1 is None or ng2 is None:
        return None
    dg = (sum(ng1) - sum(pg1), sum(ng2) - sum(pg2))
    if dg == (1, 0):
        return 1
    if dg == (0, 1):
        return 2
    if dg != (0, 0):
        return None

    p1, p2 = prev["points"]
    n1, n2 = nxt["points"]

    # Tiebreak points are numeric counters.
    if prev["is_tiebreak"] is True or nxt["is_tiebreak"] is True:
        try:
            pi1, pi2, ni1, ni2 = int(p1), int(p2), int(n1), int(n2)
        except (TypeError, ValueError):
            return None
        dp = (ni1 - pi1, ni2 - pi2)
        if dp == (1, 0):
            return 1
        if dp == (0, 1):
            return 2
        return None

    ladder = {"0": 0, "15": 1, "30": 2, "40": 3}
    if p1 in ladder and n1 in ladder and p2 == n2 and ladder[n1] == ladder[p1] + 1:
        return 1
    if p2 in ladder and n2 in ladder and p1 == n1 and ladder[n2] == ladder[p2] + 1:
        return 2

    # Deuce / advantage transitions.
    transitions = {
        ("40", "40", "A", "40"): 1,
        ("40", "40", "40", "A"): 2,
        ("A", "40", "40", "40"): 2,
        ("40", "A", "40", "40"): 1,
    }
    return transitions.get((p1, p2, n1, n2))


def _is_initial(state):
    if state["sets"] != (0, 0):
        return False
    g1, g2 = state["games"]
    if not g1 or not g2 or sum(g1) != 0 or sum(g2) != 0:
        return False
    p1, p2 = state["points"]
    return p1 in {"", "0"} and p2 in {"", "0"}


def _best_of(value):
    text = str(value or "").strip().upper()
    if text.startswith("BO"):
        return _parse_int(text[2:])
    return _parse_int(text)


def _is_terminal(state, best_of):
    if best_of not in (3, 5):
        return False
    needed = best_of // 2 + 1
    s1, s2 = state["sets"]
    if s1 is None or s2 is None:
        return False
    return max(s1, s2) == needed and s1 != s2


def _winner_from_terminal(state):
    s1, s2 = state["sets"]
    if s1 is None or s2 is None or s1 == s2:
        return None
    return 1 if s1 > s2 else 2


def _canonical_winner_name(match):
    winner_id = str(match.winner_id or "")
    if winner_id and winner_id == str(match.player1_id):
        return norm_text(match.player1_name)
    if winner_id and winner_id == str(match.player2_id):
        return norm_text(match.player2_name)
    return ""


def _resolve_candidate(candidates, meta, source_winner_name):
    if len(candidates) <= 1:
        return candidates

    surface = norm_text(meta.get("surface"))
    if surface:
        exact = [m for m in candidates if norm_text(m.surface) == surface]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact

    tournament = norm_text(meta.get("tournament"))
    if tournament:
        exact = [m for m in candidates if norm_text(m.tournament) == tournament]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact

    if source_winner_name:
        exact = [m for m in candidates if _canonical_winner_name(m) == source_winner_name]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact

    return candidates


def _load_players(path: Path):
    players = {}
    with _open_text(path) as handle:
        for row in csv.DictReader(handle):
            pid = str(row.get("player_id") or "").strip()
            name = str(row.get("name") or "").strip()
            if pid and name:
                players[pid] = {
                    "name": name,
                    "tour": str(row.get("tour") or "").strip(),
                    "sackmann_id": str(row.get("sackmann_id") or "").strip(),
                }
    return players


def _load_matches(path: Path, players):
    matches = {}
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            mid = str(row.get("match_id") or "").strip()
            p1 = players.get(str(row.get("player1_id") or "").strip())
            p2 = players.get(str(row.get("player2_id") or "").strip())
            scheduled = _parse_time(row.get("scheduled_time_utc"))
            if not mid or p1 is None or p2 is None or scheduled is None:
                continue
            matches[mid] = {
                "match_id": mid,
                "player1_name": p1["name"],
                "player2_name": p2["name"],
                "scheduled": scheduled,
                "tournament": str(row.get("tournament") or "").strip(),
                "tier_key": str(row.get("tier_key") or "").strip(),
                "surface": str(row.get("surface") or "").strip(),
                "round": str(row.get("round") or "").strip(),
                "best_of": _best_of(row.get("best_of")),
                "event_status": str(row.get("event_status") or "").strip(),
                "is_qualifying": _parse_bool(row.get("is_qualifying")),
            }
    return matches


def _iter_point_files(values: Iterable[str]):
    for value in values:
        path = Path(value)
        if any(ch in value for ch in "*?["):
            yield from sorted(path.parent.glob(path.name))
        elif path.is_file():
            yield path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--matches", required=True)
    ap.add_argument("--players", required=True)
    ap.add_argument("--points", required=True, nargs="+")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-version", default="")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    canonical, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    players = _load_players(Path(args.players))
    source_matches = _load_matches(Path(args.matches), players)
    if not source_matches:
        raise SystemExit("Live Tennis API match index is empty or unreadable")

    index = defaultdict(list)
    for match in canonical:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        index[(match.scheduled_at.date().isoformat(), pair)].append(match)

    counts = Counter()
    tape = {}
    stats = defaultdict(
        lambda: {
            1: {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0},
            2: {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0},
            "rows": 0,
            "transitions": 0,
            "duplicates": 0,
            "bad_transitions": 0,
            "missing_server": 0,
        }
    )

    point_files = list(_iter_point_files(args.points))
    if not point_files:
        raise SystemExit("No point sample files matched")

    for point_path in point_files:
        counts["point_files"] += 1
        with _open_text(point_path) as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                counts["point_state_rows"] += 1
                mid = str(row.get("match_id") or "").strip()
                if mid not in source_matches:
                    counts["point_unknown_match"] += 1
                    continue
                state = _state(row)
                if mid not in tape:
                    tape[mid] = {"first": state, "last": state, "prev": state}
                    stats[mid]["rows"] += 1
                    continue

                prev = tape[mid]["prev"]
                winner = _point_winner(prev, state)
                stats[mid]["rows"] += 1
                if winner == 0:
                    stats[mid]["duplicates"] += 1
                    counts["duplicate_states"] += 1
                elif winner not in (1, 2):
                    stats[mid]["bad_transitions"] += 1
                    counts["bad_transitions"] += 1
                else:
                    server = prev.get("server")
                    if server not in (1, 2):
                        stats[mid]["missing_server"] += 1
                        counts["missing_server_transitions"] += 1
                    else:
                        receiver = 3 - server
                        stats[mid][server]["service_points"] += 1
                        stats[mid][receiver]["return_points"] += 1
                        if winner == server:
                            stats[mid][server]["service_won"] += 1
                        else:
                            stats[mid][receiver]["return_won"] += 1
                        stats[mid]["transitions"] += 1
                        counts["point_transitions_derived"] += 1

                tape[mid]["last"] = state
                tape[mid]["prev"] = state

    before = sum(1 for match in canonical if _quality(dict(match.stats or {})))
    staged = []
    review = []

    for mid, record in tape.items():
        counts["point_matches"] += 1
        meta = source_matches[mid]
        summary = stats[mid]
        first = record["first"]
        last = record["last"]

        if not _is_initial(first):
            counts["partial_start"] += 1
            continue
        if not _is_terminal(last, meta.get("best_of")):
            counts["partial_end"] += 1
            continue
        if summary["bad_transitions"]:
            counts["transition_invalid_matches"] += 1
            continue
        if summary["missing_server"]:
            counts["server_incomplete_matches"] += 1
            continue
        if any(
            summary[side]["service_points"] <= 0 or summary[side]["return_points"] <= 0
            for side in (1, 2)
        ):
            counts["denominator_incomplete_matches"] += 1
            continue

        counts["complete_tapes"] += 1
        winner_side = _winner_from_terminal(last)
        winner_name = (
            norm_text(meta["player1_name"])
            if winner_side == 1
            else norm_text(meta["player2_name"])
            if winner_side == 2
            else ""
        )

        date = meta["scheduled"].date().isoformat()
        pair = tuple(sorted((norm_text(meta["player1_name"]), norm_text(meta["player2_name"]))))
        candidates = _resolve_candidate(list(index.get((date, pair), [])), meta, winner_name)
        if len(candidates) != 1:
            reason = "unmatched" if not candidates else "ambiguous"
            counts[reason] += 1
            if candidates:
                review.append(
                    {
                        "source_match_id": mid,
                        "reason": reason,
                        "candidate_match_ids": [str(m.match_id) for m in candidates],
                    }
                )
            continue

        match = candidates[0]
        mp1 = norm_text(match.player1_name)
        mp2 = norm_text(match.player2_name)
        sp1 = norm_text(meta["player1_name"])
        sp2 = norm_text(meta["player2_name"])
        if sp1 == mp1 and sp2 == mp2:
            mapping = ((1, "p1"), (2, "p2"))
        elif sp1 == mp2 and sp2 == mp1:
            mapping = ((1, "p2"), (2, "p1"))
        else:
            counts["orientation_failed"] += 1
            continue

        if winner_name and _canonical_winner_name(match) and winner_name != _canonical_winner_name(match):
            counts["winner_mismatch"] += 1
            review.append(
                {
                    "source_match_id": mid,
                    "reason": "winner_mismatch",
                    "match_id": str(match.match_id),
                }
            )
            continue

        incoming = {}
        for source_side, prefix in mapping:
            own = summary[source_side]
            incoming[f"{prefix}_service_points_won"] = own["service_won"] / own["service_points"]
            incoming[f"{prefix}_return_points_won"] = own["return_won"] / own["return_points"]

        existing = dict(match.stats or {})
        if _quality(existing):
            counts["already_quality_ready"] += 1
            continue

        conflicts = [
            key
            for key, value in incoming.items()
            if existing.get(key) is not None
            and abs(float(existing[key]) - float(value)) > 0.02
        ]
        if conflicts:
            counts["stat_conflict_matches"] += 1
            review.append(
                {
                    "source_match_id": mid,
                    "reason": "stat_conflicts",
                    "match_id": str(match.match_id),
                    "keys": conflicts,
                }
            )
            continue

        clean = {key: value for key, value in incoming.items() if existing.get(key) is None}
        projected = dict(existing)
        projected.update(clean)
        if not clean or not _quality(projected):
            counts["no_complete_quality_gain"] += 1
            continue

        staged.append(
            {
                "schema": 1,
                "match_id": str(match.match_id),
                "canonical": _signature(match),
                "incoming_stats": clean,
                "provenance": [
                    {
                        "source": "livetennisapi_academic_pbp",
                        "source_match_id": mid,
                        "source_version": args.source_version,
                        "license": "CC BY-NC 4.0",
                        "evidence": [
                            "full_tape_start_verified",
                            "full_tape_terminal_verified",
                            "all_point_transitions_unambiguous",
                            "server_known_for_all_points",
                            "calendar_date_exact",
                            "player_pair_exact",
                            "canonical_candidate_unique",
                        ],
                    }
                ],
                "import_ready": True,
            }
        )
        counts["staged_matches"] += 1

    report = {
        "schema": 1,
        "source": "livetennisapi_academic_pbp",
        "source_version": args.source_version,
        "license": "CC BY-NC 4.0",
        "raw_redistributed": False,
        "canonical_rows": len(canonical),
        "quality_ready_before": before,
        "quality_ready_projected_after": before + len(staged),
        "quality_ready_projected_added": len(staged),
        "counts": dict(counts),
        "production_mutated": False,
        "api_requests": 0,
        "link_policy": (
            "exact UTC calendar date + exact normalized player pair; canonical candidate "
            "must be unique; surface/tournament/winner can only disambiguate"
        ),
        "tape_policy": (
            "stage only tapes explicitly complete from 0-0 to terminal match state, "
            "with every non-duplicate transition and server identity validated"
        ),
    }

    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (out / "auto_linked.jsonl").open("w", encoding="utf-8") as handle:
        for row in staged:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "review.jsonl").open("w", encoding="utf-8") as handle:
        for row in review:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
