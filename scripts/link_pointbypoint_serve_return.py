"""Audit and stage Jeff Sackmann tennis_pointbypoint serve/return enrichment.

Source format: legacy tennis_pointbypoint single-row PBP CSVs (ATP/WTA/
Challenger/Futures/ITF, main draw and qualifying). The PBP string records point
outcomes relative to the current server and service changes in tiebreaks.

This script is read-only against canonical history. It derives only
service_points_won and return_points_won and emits the strict offline
serve-return stage schema.

Link policy: exact calendar date + exact normalized player pair. The canonical
candidate must be unique; exact tournament and winner are used only to
disambiguate duplicate same-day pair candidates. No fuzzy player/date matching.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_odds import norm_text, norm_round, norm_surface, tournament_score
from tbt.models.feature_builder import FeatureBuilder


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


def _field(row: dict, names: tuple[str, ...]):
    for name in names:
        if name in row and str(row.get(name) or "").strip():
            return row.get(name)
    return None


def _parse_date(value: object):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %y", "%d %b %Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _winner_side(value: object, *, zero_based: bool = False) -> int | None:
    text = str(value or "").strip()
    try:
        side = int(float(text))
    except (TypeError, ValueError):
        return None
    if zero_based:
        return side + 1 if side in (0, 1) else None
    return side if side in (1, 2) else None


def _source_tour(row: dict, path: Path) -> str:
    label = norm_text(row.get("tour"))
    if label in {"atp", "challenger", "itf men", "davis cup", "boys"}:
        return "atp"
    if label in {"wta", "wta 125k", "itf women", "federation cup", "girls"}:
        return "wta"
    name = path.name.lower()
    if "atp" in name:
        return "atp"
    if "wta" in name:
        return "wta"
    return ""


def _source_files(source: Path) -> list[Path]:
    files = set(source.glob("pbp_matches_*.csv"))
    # TennisVisuals validated corpus: prefer all singles files. The richer pbpx
    # files overlap a subset of pbp rows; duplicate-identical staging is handled
    # below and never double-writes canonical matches.
    files.update(source.glob("*_Singles_pbp.csv"))
    files.update(source.glob("*_Singles_pbpx.csv"))
    return sorted(files)


def _winner_name(match) -> str:
    wid = str(match.winner_id or "")
    if wid and wid == str(match.player1_id):
        return norm_text(match.player1_name)
    if wid and wid == str(match.player2_id):
        return norm_text(match.player2_name)
    return ""


def _parse_pbp(value: object):
    """Return side-relative service/return rates from one validated PBP string.

    server1 is side 1 and serves the first game. S/A mean current server won,
    R/D mean current receiver won. ';' and '.' end a game. '/' changes server
    inside a tiebreak. At the next game boundary service order is based on the
    player who started the game, not whoever served the final tiebreak point.
    """
    text = str(value or "").strip()
    if not text:
        return None

    sides = {
        1: {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0, "aces": 0, "double_faults": 0},
        2: {"service_points": 0, "service_won": 0, "return_points": 0, "return_won": 0, "aces": 0, "double_faults": 0},
    }
    game_server = 1
    current_server = 1
    game_has_points = False
    valid_points = 0
    game_wins = [0, 0]
    set_games = []
    last_point_winner = None

    for raw in text:
        if raw.isspace():
            continue
        ch = raw.upper()
        if ch in {"S", "R", "A", "D"}:
            receiver = 3 - current_server
            sides[current_server]["service_points"] += 1
            sides[receiver]["return_points"] += 1
            if ch in {"S", "A"}:
                sides[current_server]["service_won"] += 1
                last_point_winner = current_server
            else:
                sides[receiver]["return_won"] += 1
                last_point_winner = receiver
            if ch == "A":
                sides[current_server]["aces"] += 1
            elif ch == "D":
                sides[current_server]["double_faults"] += 1
            game_has_points = True
            valid_points += 1
            continue

        if ch == "/":
            if not game_has_points:
                return None
            current_server = 3 - current_server
            continue

        if ch in {";", "."}:
            if game_has_points:
                game_wins[last_point_winner - 1] += 1
                game_server = 3 - game_server
                current_server = game_server
                game_has_points = False
            if ch == "." and sum(game_wins):
                set_games.append(tuple(game_wins))
                game_wins = [0, 0]
            continue

        return None

    if game_has_points:
        game_wins[last_point_winner - 1] += 1
    if sum(game_wins):
        set_games.append(tuple(game_wins))
    if valid_points <= 0:
        return None
    if any(
        sides[side]["service_points"] <= 0 or sides[side]["return_points"] <= 0
        for side in (1, 2)
    ):
        return None

    return {
        1: {
            "service_points_won": sides[1]["service_won"] / sides[1]["service_points"],
            "return_points_won": sides[1]["return_won"] / sides[1]["return_points"],
        },
        2: {
            "service_points_won": sides[2]["service_won"] / sides[2]["service_points"],
            "return_points_won": sides[2]["return_won"] / sides[2]["return_points"],
        },
        "point_count": valid_points,
        "set_games": set_games,
        "winner_side": (
            1 if sum(a > b for a, b in set_games) > sum(b > a for a, b in set_games)
            else 2 if sum(b > a for a, b in set_games) > sum(a > b for a, b in set_games)
            else None
        ),
    }


def _pbpx_score_validated(parsed: dict, score: object) -> bool:
    """Validate reconstructed point-tape game/set scores, independent of winner label.

    TennisVisuals winner/score order need not be server1/server2 order.
    All sets must have the SAME direct or reversed orientation.
    """
    tokens = str(score or "").strip().split()
    if not 2 <= len(tokens) <= 5 or len(tokens) != len(parsed["set_games"]):
        return False
    recorded = []
    for token in tokens:
        found = re.fullmatch(r"(\\d+)(?:\\(\\d+\\))?-(\\d+)(?:\\(\\d+\\))?", token)
        if not found:
            return False
        recorded.append((int(found.group(1)), int(found.group(3))))
    sets = parsed["set_games"]
    if not all(max(a, b) >= 6 and a != b for a, b in sets):
        return False
    return (
        all(tuple(games) == expected for games, expected in zip(sets, recorded))
        or all(tuple(reversed(games)) == expected for games, expected in zip(sets, recorded))
    )


def _resolve_candidate(candidates, source_tournament: str, source_winner: str):
    if len(candidates) <= 1:
        return candidates

    tournament = norm_text(source_tournament)
    if tournament:
        exact = [m for m in candidates if norm_text(m.tournament) == tournament]
        if len(exact) == 1:
            return exact
        if exact:
            candidates = exact

    if source_winner:
        winner = [m for m in candidates if _winner_name(m) == source_winner]
        if len(winner) == 1:
            return winner
        if winner:
            candidates = winner

    return candidates


def _historical_alias_indexes(matches):
    """Use only names already attributed to an immutable canonical player ID.

    A name shared by multiple canonical IDs is *never* treated as an alias.
    Compact comparison (JoaoSousa vs Joao Sousa) has the same uniqueness gate.
    """
    exact_ids = defaultdict(set)
    compact_ids = defaultdict(set)
    by_ids_date = defaultdict(list)
    for match in matches:
        tour = str(match.tour or "").lower()
        day = match.scheduled_at.date().isoformat()
        ids = (str(match.player1_id), str(match.player2_id))
        by_ids_date[(tour, day, tuple(sorted(ids)))].append(match)
        for pid, name in ((ids[0], match.player1_name), (ids[1], match.player2_name)):
            normalized = norm_text(name)
            if not normalized or not pid:
                continue
            exact_ids[(tour, normalized)].add(pid)
            if len(normalized.replace(" ", "")) >= 8:
                compact_ids[(tour, normalized.replace(" ", ""))].add(pid)
    return exact_ids, compact_ids, by_ids_date


def _resolve_historical_alias(
    indexes, tour: str, day: str, server1: str, server2: str,
    tournament: str, surface: str, round_name: str,
):
    """Return (canonical match, side mapping, evidence) only for a unique ID pair.

    No edit-distance or partial-name match; no shift of match date.
    Compact-only matches additionally require exact event/round/surface evidence.
    """
    exact_ids, compact_ids, by_ids_date = indexes

    def find(name):
        normalized = norm_text(name)
        if not normalized:
            return None
        exact = exact_ids.get((tour, normalized), set())
        if len(exact) > 1:
            return None  # a homonym cannot be repaired by collapsing whitespace
        if len(exact) == 1:
            return next(iter(exact)), "canonical_historical_alias"
        compact = normalized.replace(" ", "")
        if len(compact) < 8:
            return None
        ids = compact_ids.get((tour, compact), set())
        if len(ids) != 1:
            return None
        return next(iter(ids)), "canonical_unique_compact_alias"

    first, second = find(server1), find(server2)
    if not first or not second or first[0] == second[0]:
        return None
    candidates = by_ids_date.get((tour, day, tuple(sorted((first[0], second[0])))), [])
    if len(candidates) != 1:
        return None
    match = candidates[0]
    compact_used = "canonical_unique_compact_alias" in (first[1], second[1])
    if compact_used:
        # Orthogonal evidence prevents "matching" a similarly named athlete.
        if not tournament or norm_text(match.tournament) != norm_text(tournament):
            return None
        if not surface or not match.surface or norm_text(surface) == "unknown":
            return None
        from tbt.data.offline_odds import norm_round, norm_surface
        if norm_surface(match.surface) != norm_surface(surface):
            return None
        if round_name and match.round_name and norm_round(round_name) != norm_round(match.round_name):
            return None
    if first[0] == str(match.player1_id) and second[0] == str(match.player2_id):
        mapping = ((1, "p1"), (2, "p2"))
    elif first[0] == str(match.player2_id) and second[0] == str(match.player1_id):
        mapping = ((1, "p2"), (2, "p1"))
    else:
        return None
    return match, mapping, (
        "canonical_unique_compact_alias" if compact_used else "canonical_historical_alias"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")

    alias_indexes = _historical_alias_indexes(matches)
    index = defaultdict(list)
    window_index = defaultdict(list)
    for match in matches:
        pair = tuple(sorted((norm_text(match.player1_name), norm_text(match.player2_name))))
        tour = str(match.tour or "").lower()
        index[(tour, match.scheduled_at.date().isoformat(), pair)].append(match)
        if str(match.match_id).startswith("hist-js:"):
            window_index[(tour, pair)].append(match)

    before = sum(1 for match in matches if _quality(dict(match.stats or {})))
    counts = Counter()
    file_counts = {}
    staged_by_match = {}
    quarantined_match_ids = set()
    review = []

    source = Path(args.source_dir)
    files = _source_files(source)
    counts["source_files"] = len(files)
    if not files:
        raise SystemExit(f"No tennis_pointbypoint CSV files found under {source}")

    for path in files:
        local = Counter()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            required_groups = (
                ("date",),
                ("server1",),
                ("server2",),
                ("pbp",),
            )
            tennisvisuals_format = {"type", "tour", "draw"}.issubset(fields)
            if any(not any(name in fields for name in group) for group in required_groups):
                raise SystemExit(f"{path}: unexpected fields={sorted(fields)}")

            for row_number, row in enumerate(reader, start=2):
                counts["source_match_rows"] += 1
                local["source_match_rows"] += 1

                source_date = _parse_date(_field(row, ("date", "match_date")))
                server1 = str(_field(row, ("server1", "player1")) or "").strip()
                server2 = str(_field(row, ("server2", "player2")) or "").strip()
                tournament = str(_field(row, ("tny_name", "tournament", "tournament_name")) or "").strip()
                source_winner_side = _winner_side(
                    _field(row, ("winner",)),
                    zero_based=tennisvisuals_format,
                )
                winner_side = source_winner_side

                if source_date is None or not server1 or not server2:
                    counts["source_identity_unusable"] += 1
                    local["source_identity_unusable"] += 1
                    continue

                parsed = _parse_pbp(_field(row, ("pbp", "points")))
                if parsed is None:
                    counts["pbp_unusable"] += 1
                    local["pbp_unusable"] += 1
                    continue
                counts["pbp_usable"] += 1
                local["pbp_usable"] += 1
                counts["point_rows_derived"] += int(parsed["point_count"])
                if tennisvisuals_format:
                    if not _pbpx_score_validated(parsed, row.get("score")) or parsed["winner_side"] is None:
                        counts["pbpx_score_unverified"] += 1
                        local["pbpx_score_unverified"] += 1
                        continue
                    winner_side = parsed["winner_side"]
                    counts["pbpx_score_validated"] += 1
                    local["pbpx_score_validated"] += 1
                    if source_winner_side != winner_side:
                        counts["pbpx_raw_winner_not_server_oriented"] += 1
                        local["pbpx_raw_winner_not_server_oriented"] += 1
                winner_name = norm_text(server1 if winner_side == 1 else server2) if winner_side in (1, 2) else ""

                pair = tuple(sorted((norm_text(server1), norm_text(server2))))
                source_tour = _source_tour(row, path)
                if not source_tour:
                    counts["source_tour_unusable"] += 1
                    local["source_tour_unusable"] += 1
                    continue
                key = (source_tour, source_date.isoformat(), pair)
                candidates = _resolve_candidate(list(index.get(key, [])), tournament, winner_name)
                alias_mapping = None
                alias_evidence = None
                if not candidates and winner_side in (1, 2):
                    resolved = _resolve_historical_alias(
                        alias_indexes, source_tour, source_date.isoformat(),
                        server1, server2, tournament,
                        str(row.get("surface") or ""),
                        str(row.get("round") or ""),
                    )
                    if resolved is not None:
                        alias_match, alias_mapping, alias_evidence = resolved
                        candidates = [alias_match]
                        counts["historical_alias_candidate"] += 1
                        local["historical_alias_candidate"] += 1
                if not candidates and tennisvisuals_format and winner_side in (1, 2):
                    # Historical hist-js timestamps can represent tournament START,
                    # not this actual match day. Audit likely matches, but NEVER
                    # attach post-match statistics to an earlier PIT timestamp.
                    window = []
                    for historical in window_index.get((source_tour, pair), []):
                        offset = (source_date - historical.scheduled_at.date()).days
                        if not 0 <= offset <= 21:
                            continue
                        if _winner_name(historical) != winner_name:
                            continue
                        if not tournament or tournament_score(tournament, historical.tournament)[0] < 1:
                            continue
                        if not historical.round_name or norm_round(historical.round_name) != norm_round(row.get("round")):
                            continue
                        if norm_surface(historical.surface) != norm_surface(row.get("surface")):
                            continue
                        window.append(historical)
                    if len(window) == 1:
                        counts["historical_window_verified"] += 1
                        local["historical_window_verified"] += 1
                        if window[0].scheduled_at.date() < source_date:
                            counts["window_pit_blocked"] += 1
                            local["window_pit_blocked"] += 1
                            continue
                        candidates = window
                    elif len(window) > 1:
                        counts["historical_window_ambiguous"] += 1
                        local["historical_window_ambiguous"] += 1
                if len(candidates) != 1:
                    reason = "unmatched" if not candidates else "ambiguous"
                    counts[reason] += 1
                    local[reason] += 1
                    if candidates:
                        review.append({
                            "source_file": path.name,
                            "source_row": row_number,
                            "reason": reason,
                            "candidate_match_ids": [str(m.match_id) for m in candidates],
                        })
                    continue

                match = candidates[0]
                mp1 = norm_text(match.player1_name)
                mp2 = norm_text(match.player2_name)
                if alias_mapping is not None:
                    mapping = alias_mapping
                elif norm_text(server1) == mp1 and norm_text(server2) == mp2:
                    mapping = ((1, "p1"), (2, "p2"))
                elif norm_text(server1) == mp2 and norm_text(server2) == mp1:
                    mapping = ((1, "p2"), (2, "p1"))
                else:
                    counts["orientation_failed"] += 1
                    local["orientation_failed"] += 1
                    continue

                expected_winner_id = (
                    str(match.player1_id if mapping[winner_side - 1][1] == "p1" else match.player2_id)
                    if winner_side in (1, 2) else ""
                )
                winner_conflict = (
                    bool(alias_mapping is not None and expected_winner_id != str(match.winner_id or ""))
                    if alias_mapping is not None
                    else bool(winner_name and _winner_name(match) and winner_name != _winner_name(match))
                )
                if winner_conflict:
                    counts["winner_mismatch"] += 1
                    local["winner_mismatch"] += 1
                    review.append({
                        "source_file": path.name,
                        "source_row": row_number,
                        "reason": "winner_mismatch",
                        "match_id": str(match.match_id),
                    })
                    continue

                incoming = {}
                for source_side, prefix in mapping:
                    incoming[f"{prefix}_service_points_won"] = parsed[source_side]["service_points_won"]
                    incoming[f"{prefix}_return_points_won"] = parsed[source_side]["return_points_won"]
                    if tennisvisuals_format and str(row.get("adf_flag") or "").strip() == "1":
                        incoming[f"{prefix}_aces"] = float(parsed[source_side]["aces"])
                        incoming[f"{prefix}_double_faults"] = float(parsed[source_side]["double_faults"])

                existing = dict(match.stats or {})
                quality_before = _quality(existing)

                conflicts = [
                    key_name
                    for key_name, value in incoming.items()
                    if existing.get(key_name) is not None
                    and abs(float(existing[key_name]) - float(value)) > 0.02
                ]
                if conflicts:
                    counts["stat_conflict_matches"] += 1
                    local["stat_conflict_matches"] += 1
                    review.append({
                        "source_file": path.name,
                        "source_row": row_number,
                        "reason": "stat_conflicts",
                        "match_id": str(match.match_id),
                        "keys": conflicts,
                    })
                    continue

                clean = {key_name: value for key_name, value in incoming.items() if existing.get(key_name) is None}
                if not clean:
                    counts["already_quality_ready" if quality_before else "already_present"] += 1
                    local["already_quality_ready" if quality_before else "already_present"] += 1
                    continue

                projected = dict(existing)
                projected.update(clean)
                if not quality_before and not _quality(projected):
                    counts["partial_only_no_quality_gain"] += 1
                    local["partial_only_no_quality_gain"] += 1
                    continue
                adds_quality = not quality_before and _quality(projected)

                match_id = str(match.match_id)
                stage = {
                    "schema": 1,
                    "match_id": match_id,
                    "canonical": _signature(match),
                    "incoming_stats": clean,
                    "provenance": [{
                        "source": (
                            "tennisvisuals_validated_pointbypoint"
                            if tennisvisuals_format
                            else "jeff_sackmann_tennis_pointbypoint"
                        ),
                        "source_file": path.name,
                        "source_row": row_number,
                        "source_date": source_date.isoformat(),
                        "score_validated": bool(tennisvisuals_format),
                        "evidence": [
                            "calendar_date_exact" if match.scheduled_at.date() == source_date else "historical_window_date_guarded",
                            "player_pair_exact" if alias_mapping is None else "player_pair_canonical_alias",
                            "canonical_candidate_unique",
                            * (["winner_derived_from_point_tape", "full_set_score_matches_point_tape"] if tennisvisuals_format else []),
                            *([alias_evidence] if alias_evidence else []),
                            "explicit_pbp_server_relative_outcomes",
                        ],
                    }],
                    "quality_ready_added": adds_quality,
                    "import_ready": True,
                }

                if match_id in quarantined_match_ids:
                    counts["source_duplicate_quarantined"] += 1
                    local["source_duplicate_quarantined"] += 1
                    continue
                previous = staged_by_match.get(match_id)
                if previous is not None:
                    if previous["incoming_stats"] == stage["incoming_stats"]:
                        counts["source_duplicate_same"] += 1
                        local["source_duplicate_same"] += 1
                    else:
                        counts["source_duplicate_conflict"] += 1
                        local["source_duplicate_conflict"] += 1
                        review.append({
                            "source_file": path.name,
                            "source_row": row_number,
                            "reason": "source_duplicate_conflict",
                            "match_id": match_id,
                        })
                        staged_by_match.pop(match_id, None)
                        quarantined_match_ids.add(match_id)
                    continue

                staged_by_match[match_id] = stage
                counts["staged_matches"] += 1
                local["staged_matches"] += 1
                counts["staged_stat_fields"] += len(clean)
                local["staged_stat_fields"] += len(clean)
                if adds_quality:
                    counts["staged_quality_ready_added"] += 1
                    local["staged_quality_ready_added"] += 1

        file_counts[path.name] = dict(local)

    staged = list(staged_by_match.values())
    projected_added = sum(1 for entry in staged if entry.get("quality_ready_added") is True)
    report = {
        "schema": 1,
        "canonical_rows": len(matches),
        "quality_ready_before": before,
        "quality_ready_projected_after": before + projected_added,
        "quality_ready_projected_added": projected_added,
        "counts": dict(counts),
        "file_counts": file_counts,
        "production_mutated": False,
        "api_requests": 0,
        "source_policy": (
            "Legacy Jeff Sackmann tennis_pointbypoint plus the operator-supplied TennisVisuals "
            "validated single-row PBP corpus. Only derived service/return rates are staged; "
            "raw point tapes are not redistributed by this workflow."
        ),
        "link_policy": (
            "exact calendar date + exact normalized player pair; canonical candidate must be unique; "
            "exact tournament/winner may only disambiguate same-day duplicate candidates"
        ),
    }

    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for name, rows in (("auto_linked.jsonl", staged), ("review.jsonl", review)):
        with (out / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
