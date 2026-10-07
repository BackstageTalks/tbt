"""Integrate four audited Kaggle tennis sources into BlinQ research sidecars.

This job is intentionally sidecar-only:
- WTA weekly singles/doubles rankings become point-in-time candidate history.
- LiveTennis point states become canonical-match keyed timestamped PBP research.
- Pinnacle sample becomes pre-start market-path / CLV research.
- Wimbledon 2024 becomes canonical-match keyed point and match research.

No canonical MatchRecord mutation, provider API request, or model promotion occurs.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_round, norm_surface, norm_text, round_evidence, tournament_score


def _norm_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _parse_date(value: object):
    text = _clean_text(value)
    if not text:
        return None
    candidates = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for fmt in candidates:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _parse_dt(value: object):
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError:
        result = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                result = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
    if result is None:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _int(value: object):
    if value in (None, ""):
        return None
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return number


def _float(value: object):
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: object):
    text = norm_text(value)
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class JsonlGzipWriter:
    def __init__(self, path: Path):
        self.path = path
        self.handle = gzip.open(path, "wt", encoding="utf-8", compresslevel=6)
        self.rows = 0

    def write(self, row: dict[str, Any]) -> None:
        self.handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        self.rows += 1

    def close(self) -> None:
        self.handle.close()


def _canonical_indexes(matches):
    name_ids: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    global_name_ids: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    date_pair: dict[tuple[str, tuple[str, str]], list[Any]] = defaultdict(list)
    year_pair: dict[tuple[int, tuple[str, str]], list[Any]] = defaultdict(list)
    for match in matches:
        tour = norm_text(match.tour)
        for pid, name in ((match.player1_id, match.player1_name), (match.player2_id, match.player2_name)):
            key = _norm_name(name)
            if key and pid:
                name_ids[(tour, key)].add((str(pid), str(name)))
                global_name_ids[key].add((str(pid), str(name), tour))
        pair = tuple(sorted((_norm_name(match.player1_name), _norm_name(match.player2_name))))
        if pair[0] and pair[1] and pair[0] != pair[1]:
            date_pair[(match.scheduled_at.date().isoformat(), pair)].append(match)
            year_pair[(int(match.scheduled_at.year), pair)].append(match)
    return name_ids, global_name_ids, date_pair, year_pair


def _unique_canonical_player(
    name: object,
    *,
    tour: object,
    name_ids,
    global_name_ids,
):
    key = _norm_name(name)
    t = norm_text(tour)
    if t in {"atp", "wta"}:
        values = name_ids.get((t, key), set())
        if len(values) == 1:
            pid, canonical_name = next(iter(values))
            return {"canonical_player_id": pid, "canonical_player_name": canonical_name, "tour": t}
        if len(values) > 1:
            return None
    values = global_name_ids.get(key, set())
    if len(values) == 1:
        pid, canonical_name, canonical_tour = next(iter(values))
        return {
            "canonical_player_id": pid,
            "canonical_player_name": canonical_name,
            "tour": canonical_tour,
        }
    return None


def _candidate_match(
    *,
    source_date,
    player1,
    player2,
    tour,
    tournament,
    surface,
    round_name,
    date_pair,
):
    pair = tuple(sorted((_norm_name(player1), _norm_name(player2))))
    if not pair[0] or not pair[1] or pair[0] == pair[1] or source_date is None:
        return None, "invalid_identity"
    candidates = []
    for delta in (0, -1, 1):
        day = source_date
        if delta:
            from datetime import timedelta
            day = source_date + timedelta(days=delta)
        for match in date_pair.get((day.isoformat(), pair), []):
            score = 4 if delta == 0 else 1
            evidence = ["date_exact" if delta == 0 else "date_plusminus_1"]
            source_tour = norm_text(tour)
            target_tour = norm_text(match.tour)
            if source_tour in {"atp", "wta"}:
                if source_tour != target_tour:
                    continue
                score += 2
                evidence.append("tour")
            if tournament:
                tscore, te = tournament_score(tournament, match.tournament)
                if tscore <= 0:
                    continue
                score += tscore
                evidence.append(te)
            ss, cs = norm_surface(surface), norm_surface(match.surface)
            if ss not in {"", "unknown"} and cs not in {"", "unknown"}:
                if ss != cs:
                    continue
                score += 1
                evidence.append("surface")
            if round_name:
                rscore, re = round_evidence(round_name, match.round_name)
                if rscore < 0:
                    continue
                score += rscore
                evidence.append(re)
            candidates.append((score, str(match.match_id), match, evidence))
    if not candidates:
        return None, "unmatched"
    candidates.sort(key=lambda item: item[0], reverse=True)
    top_score = candidates[0][0]
    top = [item for item in candidates if item[0] == top_score]
    if len(top) != 1:
        return None, "ambiguous"
    _, _, match, evidence = top[0]
    return (match, evidence), None


def _file_meta(path: Path, rows: int) -> dict[str, Any]:
    return {
        "name": path.name,
        "rows": int(rows),
        "bytes": int(path.stat().st_size),
        "sha256": _sha256(path),
    }


def integrate_wta(
    players_path: Path,
    singles_path: Path,
    doubles_path: Path,
    out: Path,
    *,
    name_ids,
    global_name_ids,
):
    counts = Counter()
    source_players: dict[str, dict[str, str]] = {}
    source_name_dupes = Counter()
    with players_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"playerId", "fullName", "dateOfBirth"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"WTA players missing columns: {sorted(missing)}")
        by_name = Counter()
        raw_rows = []
        for row in reader:
            counts["players_source_rows"] += 1
            pid = _clean_text(row.get("playerId"))
            name = _clean_text(row.get("fullName"))
            if not pid or not name:
                counts["players_invalid"] += 1
                continue
            by_name[_norm_name(name)] += 1
            raw_rows.append((pid, row))
        conflicting_source_ids = set()
        for pid, row in raw_rows:
            name = _clean_text(row.get("fullName"))
            key = _norm_name(name)
            if by_name[key] != 1:
                source_name_dupes[key] += 1
                counts["players_source_name_ambiguous"] += 1
                continue
            canonical = _unique_canonical_player(
                name, tour="wta", name_ids=name_ids, global_name_ids=global_name_ids
            )
            if canonical is None or canonical["tour"] != "wta":
                counts["players_unmapped"] += 1
                continue
            candidate = {
                "source_player_id": pid,
                "source_name": name,
                "canonical_player_id": canonical["canonical_player_id"],
                "canonical_player_name": canonical["canonical_player_name"],
                "country_code": _clean_text(row.get("countryCode")),
                "date_of_birth": _clean_text(row.get("dateOfBirth")),
            }
            previous = source_players.get(pid)
            if previous is None:
                source_players[pid] = candidate
            elif previous == candidate:
                counts["players_duplicate_source_id_rows"] += 1
            else:
                conflicting_source_ids.add(pid)
                counts["players_conflicting_source_id_rows"] += 1
        for pid in conflicting_source_ids:
            source_players.pop(pid, None)
        counts["players_conflicting_source_ids"] = len(conflicting_source_ids)
        counts["players_safe_mapped"] = len(source_players)

    cross_path = out / "wta-player-crosswalk.jsonl.gz"
    cross = JsonlGzipWriter(cross_path)
    for pid in sorted(source_players, key=lambda x: (len(x), x)):
        cross.write({"schema": 1, **source_players[pid], "mapping_policy": "unique_exact_normalized_name"})
    cross.close()

    files = [_file_meta(cross_path, cross.rows)]
    for ranking_type, path in (("singles", singles_path), ("doubles", doubles_path)):
        target = out / f"wta-rankings-{ranking_type}.jsonl.gz"
        conflict_target = out / f"wta-rankings-{ranking_type}-conflicts.jsonl.gz"

        # First pass establishes one signature per player/date and identifies
        # every conflicting key. Conflicting snapshots are excluded wholesale:
        # source row order must never decide which historical rank survives.
        seen: dict[tuple[str, str], tuple[Any, ...]] = {}
        conflict_keys: set[tuple[str, str]] = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"ranking", "playerId", "points", "tournamentsPlayed", "movement", "rankedAt"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"WTA {ranking_type} rankings missing columns: {sorted(missing)}")
            for row in reader:
                counts[f"{ranking_type}_source_rows"] += 1
                pid = _clean_text(row.get("playerId"))
                mapped = source_players.get(pid)
                if mapped is None:
                    counts[f"{ranking_type}_unmapped_player_rows"] += 1
                    continue
                ranked = _parse_date(row.get("rankedAt"))
                rank = _int(row.get("ranking"))
                if ranked is None or rank is None or rank <= 0:
                    counts[f"{ranking_type}_invalid_rows"] += 1
                    continue
                signature = (
                    rank,
                    _int(row.get("points")),
                    _int(row.get("tournamentsPlayed")),
                    _int(row.get("movement")),
                )
                key = (pid, ranked.isoformat())
                previous = seen.get(key)
                if previous is None:
                    seen[key] = signature
                elif previous == signature:
                    counts[f"{ranking_type}_duplicate_rows"] += 1
                else:
                    conflict_keys.add(key)
                    counts[f"{ranking_type}_conflict_observations"] += 1

        counts[f"{ranking_type}_conflicting_snapshot_keys"] = len(conflict_keys)

        writer = JsonlGzipWriter(target)
        conflict_writer = JsonlGzipWriter(conflict_target)
        emitted: set[tuple[str, str]] = set()
        conflict_rows_seen: set[tuple[tuple[str, str], tuple[Any, ...]]] = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pid = _clean_text(row.get("playerId"))
                mapped = source_players.get(pid)
                if mapped is None:
                    continue
                ranked = _parse_date(row.get("rankedAt"))
                rank = _int(row.get("ranking"))
                if ranked is None or rank is None or rank <= 0:
                    continue
                signature = (
                    rank,
                    _int(row.get("points")),
                    _int(row.get("tournamentsPlayed")),
                    _int(row.get("movement")),
                )
                key = (pid, ranked.isoformat())
                if key in conflict_keys:
                    conflict_key = (key, signature)
                    if conflict_key not in conflict_rows_seen:
                        conflict_rows_seen.add(conflict_key)
                        conflict_writer.write({
                            "schema": 1,
                            "ranking_type": ranking_type,
                            "ranked_at": ranked.isoformat(),
                            "ranking": rank,
                            "points": signature[1],
                            "tournaments_played": signature[2],
                            "movement": signature[3],
                            **mapped,
                            "quarantine_reason": "conflicting_same_player_same_ranked_at",
                        })
                    counts[f"{ranking_type}_conflict_rows_excluded"] += 1
                    continue
                if key in emitted:
                    continue
                emitted.add(key)
                writer.write({
                    "schema": 1,
                    "ranking_type": ranking_type,
                    "ranked_at": ranked.isoformat(),
                    "ranking": rank,
                    "points": signature[1],
                    "tournaments_played": signature[2],
                    "movement": signature[3],
                    **mapped,
                    "feature_policy": "candidate_only; require ranked_at strictly before match date",
                })
                counts[f"{ranking_type}_sidecar_rows"] += 1
        writer.close()
        conflict_writer.close()
        files.append(_file_meta(target, writer.rows))
        files.append(_file_meta(conflict_target, conflict_writer.rows))

    return {
        "status": "integrated_research_sidecar",
        "counts": dict(counts),
        "files": files,
        "model_policy": "candidate_only_not_promoted",
        "point_in_time_policy": "ranked_at must be strictly before match date",
    }


def integrate_live(
    players_path: Path,
    matches_path: Path,
    points_path: Path,
    out: Path,
    *,
    name_ids,
    global_name_ids,
    date_pair,
):
    counts = Counter()
    players = {}
    player_cross = {}
    with players_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"player_id", "name", "tour", "sackmann_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Live players missing columns: {sorted(missing)}")
        source_name_counts = Counter()
        raw = []
        for row in reader:
            counts["players_source_rows"] += 1
            pid = _clean_text(row.get("player_id"))
            name = _clean_text(row.get("name"))
            if not pid or not name:
                continue
            source_name_counts[(norm_text(row.get("tour")), _norm_name(name))] += 1
            raw.append((pid, row))
        for pid, row in raw:
            players[pid] = row
            tour = norm_text(row.get("tour"))
            name = _clean_text(row.get("name"))
            if source_name_counts[(tour, _norm_name(name))] != 1:
                counts["players_source_name_ambiguous"] += 1
                continue
            canonical = _unique_canonical_player(
                name, tour=tour, name_ids=name_ids, global_name_ids=global_name_ids
            )
            if canonical is None:
                counts["players_unmapped"] += 1
                continue
            player_cross[pid] = {
                "source_player_id": pid,
                "source_name": name,
                "source_tour": tour,
                "source_sackmann_id": _clean_text(row.get("sackmann_id")),
                "canonical_player_id": canonical["canonical_player_id"],
                "canonical_player_name": canonical["canonical_player_name"],
                "canonical_tour": canonical["tour"],
            }
            counts["players_safe_mapped"] += 1

    cross_path = out / "livetennis-player-crosswalk.jsonl.gz"
    cross_writer = JsonlGzipWriter(cross_path)
    for pid in sorted(player_cross):
        cross_writer.write({"schema": 1, **player_cross[pid], "mapping_policy": "unique_exact_normalized_name"})
    cross_writer.close()

    point_match_ids = set()
    with points_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"match_id", "sets_p1", "sets_p2", "games_p1", "games_p2", "points_p1", "points_p2", "server", "is_tiebreak", "timestamp_utc"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Live PBP missing columns: {sorted(missing)}")
        for row in reader:
            counts["points_source_rows"] += 1
            mid = _clean_text(row.get("match_id"))
            if mid:
                point_match_ids.add(mid)
    counts["point_source_matches"] = len(point_match_ids)

    mapped_matches = {}
    match_cross_path = out / "livetennis-match-crosswalk.jsonl.gz"
    match_writer = JsonlGzipWriter(match_cross_path)
    with matches_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"match_id", "player1_id", "player2_id", "tournament", "surface", "round", "scheduled_time_utc"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Live matches missing columns: {sorted(missing)}")
        for row in reader:
            source_mid = _clean_text(row.get("match_id"))
            if source_mid not in point_match_ids:
                continue
            counts["point_match_metadata_rows"] += 1
            p1_id = _clean_text(row.get("player1_id"))
            p2_id = _clean_text(row.get("player2_id"))
            p1 = players.get(p1_id)
            p2 = players.get(p2_id)
            if not p1 or not p2:
                counts["match_missing_player"] += 1
                continue
            p1_name = _clean_text(p1.get("name"))
            p2_name = _clean_text(p2.get("name"))
            tours = {norm_text(p1.get("tour")), norm_text(p2.get("tour"))} - {""}
            tour = next(iter(tours)) if len(tours) == 1 else ""
            source_date = _parse_date(row.get("scheduled_time_utc"))
            linked, reason = _candidate_match(
                source_date=source_date,
                player1=p1_name,
                player2=p2_name,
                tour=tour,
                tournament=_clean_text(row.get("tournament")),
                surface=_clean_text(row.get("surface")),
                round_name=_clean_text(row.get("round")),
                date_pair=date_pair,
            )
            if linked is None:
                fallback, _ = _candidate_match(
                    source_date=source_date,
                    player1=p1_name,
                    player2=p2_name,
                    tour=tour,
                    tournament="",
                    surface=_clean_text(row.get("surface")),
                    round_name="",
                    date_pair=date_pair,
                )
                if fallback is not None and "date_exact" in fallback[1]:
                    linked = fallback
                    counts["matches_exact_pair_context_fallback"] += 1
                else:
                    counts[f"match_{reason}"] += 1
                    continue
            match, evidence = linked
            mapped_matches[source_mid] = {
                "canonical_match_id": str(match.match_id),
                "canonical_player1_id": str(match.player1_id),
                "canonical_player2_id": str(match.player2_id),
                "canonical_scheduled_date": match.scheduled_at.date().isoformat(),
            }
            match_writer.write({
                "schema": 1,
                "source_match_id": source_mid,
                **mapped_matches[source_mid],
                "source_player1_id": p1_id,
                "source_player2_id": p2_id,
                "source_player1_name": p1_name,
                "source_player2_name": p2_name,
                "identity_evidence": evidence,
                "mapping_policy": "date_pair_tournament_surface_round_fail_closed",
            })
            counts["matches_safe_mapped"] += 1
    match_writer.close()

    points_out = out / "livetennis-points-2026-06.jsonl.gz"
    point_writer = JsonlGzipWriter(points_out)
    seen_points = set()
    with points_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_mid = _clean_text(row.get("match_id"))
            mapped = mapped_matches.get(source_mid)
            if mapped is None:
                continue
            timestamp = _parse_dt(row.get("timestamp_utc"))
            if timestamp is None:
                counts["points_invalid_timestamp"] += 1
                continue
            key = (
                source_mid,
                timestamp.isoformat(),
                _clean_text(row.get("sets_p1")),
                _clean_text(row.get("sets_p2")),
                _clean_text(row.get("games_p1")),
                _clean_text(row.get("games_p2")),
                _clean_text(row.get("points_p1")),
                _clean_text(row.get("points_p2")),
                _clean_text(row.get("server")),
            )
            if key in seen_points:
                counts["points_duplicate_rows"] += 1
                continue
            seen_points.add(key)
            point_writer.write({
                "schema": 1,
                "source_match_id": source_mid,
                **mapped,
                "timestamp_utc": timestamp.isoformat(),
                "sets_p1": _int(row.get("sets_p1")),
                "sets_p2": _int(row.get("sets_p2")),
                "games_p1": _int(row.get("games_p1")),
                "games_p2": _int(row.get("games_p2")),
                "points_p1": _clean_text(row.get("points_p1")),
                "points_p2": _clean_text(row.get("points_p2")),
                "server": _clean_text(row.get("server")),
                "is_tiebreak": _bool(row.get("is_tiebreak")),
                "model_policy": "research_only_in_play_observation; never a pre_match feature",
            })
            counts["points_sidecar_rows"] += 1
    point_writer.close()

    return {
        "status": "integrated_research_sidecar",
        "counts": dict(counts),
        "files": [
            _file_meta(cross_path, cross_writer.rows),
            _file_meta(match_cross_path, match_writer.rows),
            _file_meta(points_out, point_writer.rows),
        ],
        "model_policy": "research_only_not_promoted",
        "timestamp_policy": "observed timestamped in-play states; not pre-match features",
    }


def _pinnacle_names(row: dict[str, str], premium: bool):
    if premium:
        p1 = " ".join(x for x in (_clean_text(row.get("Player1_Firstname")), _clean_text(row.get("Player1_Surname"))) if x)
        p2 = " ".join(x for x in (_clean_text(row.get("Player2_Firstname")), _clean_text(row.get("Player2_Surname"))) if x)
    else:
        p1 = _clean_text(row.get("Player1_Name"))
        p2 = _clean_text(row.get("Player2_Name"))
    return p1, p2


def integrate_pinnacle(
    premium_path: Path,
    pure_path: Path,
    out: Path,
    *,
    date_pair,
):
    counts = Counter()
    source_map = {}
    source_evidence = {}

    def map_row(row, premium):
        source_mid = _clean_text(row.get("Match_ID"))
        p1, p2 = _pinnacle_names(row, premium)
        source_date = _parse_date(row.get("Start_Time_UTC")) or _parse_date(row.get("Date"))
        linked, reason = _candidate_match(
            source_date=source_date,
            player1=p1,
            player2=p2,
            tour=_clean_text(row.get("Tour")),
            tournament=_clean_text(row.get("Tournament")),
            surface=_clean_text(row.get("Surface")),
            round_name=_clean_text(row.get("Stage")),
            date_pair=date_pair,
        )
        if linked is None:
            fallback, _ = _candidate_match(
                source_date=source_date,
                player1=p1,
                player2=p2,
                tour=_clean_text(row.get("Tour")),
                tournament="",
                surface=_clean_text(row.get("Surface")),
                round_name="",
                date_pair=date_pair,
            )
            if fallback is not None and "date_exact" in fallback[1]:
                linked = fallback
                counts["exact_pair_context_fallback_rows"] += 1
            else:
                counts[f"match_{reason}"] += 1
                return None
        match, evidence = linked
        previous = source_map.get(source_mid)
        if previous is not None and previous != str(match.match_id):
            counts["source_match_mapping_conflicts"] += 1
            return None
        source_map[source_mid] = str(match.match_id)
        source_evidence[source_mid] = evidence
        return match

    with pure_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts["pure_source_rows"] += 1
            if map_row(row, False) is not None:
                counts["pure_mapped_rows"] += 1
    with premium_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts["premium_source_rows"] += 1
            if map_row(row, True) is not None:
                counts["premium_mapped_rows"] += 1

    if counts["source_match_mapping_conflicts"]:
        raise ValueError("Pinnacle source match identity conflict")

    path_out = out / "pinnacle-market-path.jsonl.gz"
    writer = JsonlGzipWriter(path_out)
    with premium_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_mid = _clean_text(row.get("Match_ID"))
            canonical_mid = source_map.get(source_mid)
            if not canonical_mid:
                continue
            start = _parse_dt(row.get("Start_Time_UTC"))
            snap = _parse_dt(row.get("Snapshot_Timestamp"))
            if start is not None and snap is not None and snap > start:
                counts["premium_post_start_snapshot_excluded"] += 1
                continue
            p1, p2 = _pinnacle_names(row, True)
            writer.write({
                "schema": 1,
                "canonical_match_id": canonical_mid,
                "source_match_id": source_mid,
                "player1_name": p1,
                "player2_name": p2,
                "start_time_utc": start.isoformat() if start else None,
                "snapshot_timestamp_utc": snap.isoformat() if snap else None,
                "hours_to_match": _float(row.get("Hours_To_Match")),
                "snapshot_type": _clean_text(row.get("Snapshot_Type")),
                "snapshot_n": _int(row.get("Snapshot_N")),
                "snapshot_total_count": _int(row.get("Snapshot_Total_Count")),
                "pinnacle_odds_p1": _float(row.get("Pinnacle_Odd_P1")),
                "pinnacle_odds_p2": _float(row.get("Pinnacle_Odd_P2")),
                "opening_p1": _float(row.get("Pinnacle_Opening_P1")),
                "opening_p2": _float(row.get("Pinnacle_Opening_P2")),
                "opening_timestamp": _clean_text(row.get("Pinnacle_Opening_Timestamp")),
                "closing_p1": _float(row.get("Pinnacle_Closing_P1")),
                "closing_p2": _float(row.get("Pinnacle_Closing_P2")),
                "highest_p1": _float(row.get("Pinnacle_Highest_P1")),
                "highest_p1_timestamp": _clean_text(row.get("Pinnacle_Highest_P1_Timestamp")),
                "lowest_p1": _float(row.get("Pinnacle_Lowest_P1")),
                "lowest_p1_timestamp": _clean_text(row.get("Pinnacle_Lowest_P1_Timestamp")),
                "highest_p2": _float(row.get("Pinnacle_Highest_P2")),
                "highest_p2_timestamp": _clean_text(row.get("Pinnacle_Highest_P2_Timestamp")),
                "lowest_p2": _float(row.get("Pinnacle_Lowest_P2")),
                "lowest_p2_timestamp": _clean_text(row.get("Pinnacle_Lowest_P2_Timestamp")),
                "opening_margin_pct": _float(row.get("Pinnacle_Margin_Opening_Pct")),
                "closing_margin_pct": _float(row.get("Pinnacle_Margin_Closing_Pct")),
                "no_vig_open_p1": _float(row.get("NoVig_Open_P1")),
                "no_vig_open_p2": _float(row.get("NoVig_Open_P2")),
                "no_vig_close_p1": _float(row.get("NoVig_Close_P1")),
                "no_vig_close_p2": _float(row.get("NoVig_Close_P2")),
                "movement_from_open_p1_pct": _float(row.get("Move_From_Opening_P1_Pct")),
                "movement_from_open_p2_pct": _float(row.get("Move_From_Opening_P2_Pct")),
                "volatility_p1": _float(row.get("Snapshot_Volatility_P1")),
                "volatility_p2": _float(row.get("Snapshot_Volatility_P2")),
                "identity_evidence": source_evidence.get(source_mid),
                "model_policy": "research_clv_only; outcome_ai_score_fields_excluded",
            })
            counts["premium_sidecar_rows"] += 1
    writer.close()

    summary_out = out / "pinnacle-market-summary.jsonl.gz"
    summary_writer = JsonlGzipWriter(summary_out)
    with pure_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source_mid = _clean_text(row.get("Match_ID"))
            canonical_mid = source_map.get(source_mid)
            if not canonical_mid:
                continue
            summary_writer.write({
                "schema": 1,
                "canonical_match_id": canonical_mid,
                "source_match_id": source_mid,
                "start_time_utc": (_parse_dt(row.get("Start_Time_UTC")) or datetime.min.replace(tzinfo=timezone.utc)).isoformat(),
                "p1_opening_odds": _float(row.get("P1_Opening_Odds")),
                "p1_closing_odds": _float(row.get("P1_Closing_Odds")),
                "p1_movement_pct": _float(row.get("P1_Movement_Pct")),
                "p2_opening_odds": _float(row.get("P2_Opening_Odds")),
                "p2_closing_odds": _float(row.get("P2_Closing_Odds")),
                "p2_movement_pct": _float(row.get("P2_Movement_Pct")),
                "snapshots_count": _int(row.get("Snapshots_Count")),
                "identity_evidence": source_evidence.get(source_mid),
                "model_policy": "research_clv_only; closing_not_prematch_feature",
            })
            counts["pure_sidecar_rows"] += 1
    summary_writer.close()

    return {
        "status": "integrated_research_sidecar",
        "counts": dict(counts),
        "files": [_file_meta(path_out, writer.rows), _file_meta(summary_out, summary_writer.rows)],
        "model_policy": "research_clv_only_not_promoted",
    }


def integrate_wimbledon(
    points_path: Path,
    match_path: Path,
    out: Path,
    *,
    year_pair,
):
    counts = Counter()
    source_map = {}
    source_evidence = {}

    match_out = out / "wimbledon-2024-match-level.jsonl.gz"
    match_writer = JsonlGzipWriter(match_out)
    with match_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"match_id", "Player1Name", "Player2Name", "Year"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Wimbledon match level missing columns: {sorted(missing)}")
        for row in reader:
            counts["match_source_rows"] += 1
            source_mid = _clean_text(row.get("match_id"))
            year = _int(row.get("Year"))
            pair = tuple(sorted((_norm_name(row.get("Player1Name")), _norm_name(row.get("Player2Name")))))
            candidates = [
                m for m in year_pair.get((year or 2024, pair), [])
                if "wimbledon" in norm_text(m.tournament)
            ]
            if len(candidates) != 1:
                counts["match_ambiguous_or_unmatched"] += 1
                continue
            match = candidates[0]
            source_map[source_mid] = str(match.match_id)
            evidence = ["year", "pair", "tournament_wimbledon"]
            source_evidence[source_mid] = evidence
            match_writer.write({
                "schema": 1,
                "canonical_match_id": str(match.match_id),
                "source_match_id": source_mid,
                "player1_name": _clean_text(row.get("Player1Name")),
                "player2_name": _clean_text(row.get("Player2Name")),
                "player1_aces": _int(row.get("Player1Ace")),
                "player2_aces": _int(row.get("Player2Ace")),
                "player1_double_faults": _int(row.get("Player1DoubleFault")),
                "player2_double_faults": _int(row.get("Player2DoubleFault")),
                "player1_unforced_errors": _int(row.get("Player1UnforcedError")),
                "player2_unforced_errors": _int(row.get("Player2UnforcedError")),
                "player1_net_points": _int(row.get("Player1NetPoint")),
                "player1_net_points_won": _int(row.get("Player1NetPointWon")),
                "player2_net_points": _int(row.get("Player2NetPoint")),
                "player2_net_points_won": _int(row.get("Player2NetPointWon")),
                "rally_duration_seconds": _float(row.get("RallyDurationSeconds")),
                "identity_evidence": evidence,
                "model_policy": "research_only_postmatch_aggregate; not a prematch feature",
            })
            counts["match_sidecar_rows"] += 1
    match_writer.close()

    points_out = out / "wimbledon-2024-points.jsonl.gz"
    writer = JsonlGzipWriter(points_out)
    seen = set()
    with points_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"match_id", "SetNumber", "GameNumber", "PointNumberInGame", "Player1Name", "Player2Name"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Wimbledon points missing columns: {sorted(missing)}")
        for row in reader:
            counts["point_source_rows"] += 1
            source_mid = _clean_text(row.get("match_id"))
            canonical_mid = source_map.get(source_mid)
            if not canonical_mid:
                counts["point_unmapped_match_rows"] += 1
                continue
            key = (
                source_mid,
                _clean_text(row.get("SetNumber")),
                _clean_text(row.get("GameNumber")),
                _clean_text(row.get("PointNumberInGame")),
            )
            if key in seen:
                counts["point_duplicate_rows"] += 1
                continue
            seen.add(key)
            writer.write({
                "schema": 1,
                "canonical_match_id": canonical_mid,
                "source_match_id": source_mid,
                "set_number": _int(row.get("SetNumber")),
                "game_number": _int(row.get("GameNumber")),
                "point_number_in_game": _int(row.get("PointNumberInGame")),
                "point_winner_player": _clean_text(row.get("PointWinnerPlayer")),
                "point_server_player": _clean_text(row.get("PointServerPlayer")),
                "serve_speed_kmh": _float(row.get("ServeSpeedKMH")),
                "serve_number": _int(row.get("ServeNumber")),
                "serve_width": _clean_text(row.get("ServeWidth")),
                "serve_depth": _clean_text(row.get("ServeDepth")),
                "return_depth": _clean_text(row.get("ReturnDepth")),
                "rally_count": _int(row.get("RallyCount")),
                "rally_duration_seconds": _float(row.get("RallyDurationSeconds")),
                "point_end_type": _clean_text(row.get("PointEndType")),
                "winner_shot_type": _clean_text(row.get("WinnerShotType")),
                "is_break_point": _bool(row.get("IsBreakPointPoint")),
                "is_ace": _bool(row.get("IsAcePoint")),
                "is_double_fault": _bool(row.get("IsDoubleFaultPoint")),
                "is_winner": _bool(row.get("IsWinnerPoint")),
                "player1_distance_run": _float(row.get("Player1DistanceRun")),
                "player2_distance_run": _float(row.get("Player2DistanceRun")),
                "player1_score": _clean_text(row.get("Player1Score")),
                "player2_score": _clean_text(row.get("Player2Score")),
                "standard_score": _clean_text(row.get("StandardScore")),
                "identity_evidence": source_evidence.get(source_mid),
                "model_policy": "research_only_point_context; momentum_and_match_winner_fields_excluded",
            })
            counts["point_sidecar_rows"] += 1
    writer.close()

    return {
        "status": "integrated_research_sidecar",
        "counts": dict(counts),
        "files": [_file_meta(match_out, match_writer.rows), _file_meta(points_out, writer.rows)],
        "model_policy": "research_only_not_promoted",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--wta-players", required=True)
    ap.add_argument("--wta-singles", required=True)
    ap.add_argument("--wta-doubles", required=True)
    ap.add_argument("--live-players", required=True)
    ap.add_argument("--live-matches", required=True)
    ap.add_argument("--live-points", required=True)
    ap.add_argument("--pinnacle-premium", required=True)
    ap.add_argument("--pinnacle-pure", required=True)
    ap.add_argument("--wimbledon-points", required=True)
    ap.add_argument("--wimbledon-matches", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    matches, identity = sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if identity.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")
    name_ids, global_name_ids, date_pair, year_pair = _canonical_indexes(matches)

    wta = integrate_wta(
        Path(args.wta_players),
        Path(args.wta_singles),
        Path(args.wta_doubles),
        out,
        name_ids=name_ids,
        global_name_ids=global_name_ids,
    )
    live = integrate_live(
        Path(args.live_players),
        Path(args.live_matches),
        Path(args.live_points),
        out,
        name_ids=name_ids,
        global_name_ids=global_name_ids,
        date_pair=date_pair,
    )
    pinnacle = integrate_pinnacle(
        Path(args.pinnacle_premium),
        Path(args.pinnacle_pure),
        out,
        date_pair=date_pair,
    )
    wimbledon = integrate_wimbledon(
        Path(args.wimbledon_points),
        Path(args.wimbledon_matches),
        out,
        year_pair=year_pair,
    )

    files = []
    for section in (wta, live, pinnacle, wimbledon):
        files.extend(section.get("files") or [])
    report = {
        "schema": 1,
        "status": "ready_to_publish_research_sidecars",
        "canonical_rows": len(matches),
        "identity_safety": identity,
        "wta_rankings": wta,
        "livetennis_pbp": live,
        "pinnacle_sample": pinnacle,
        "wimbledon_2024": wimbledon,
        "files": files,
        "canonical_match_mutated": False,
        "provider_api_requests": 0,
        "model_promoted": False,
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
