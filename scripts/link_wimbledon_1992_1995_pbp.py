"""Fail-closed linker for the CC BY 4.0 Wimbledon 1992-1995 point dataset.

Source:
  Klaassen & Magnus, "Analyzing Wimbledon - The Power of Statistics"
  DOI 10.21942/uva.21983555, version 3.

The workbook has two rows per match in MatchData_{Men,Women} (player I/J)
and point-level rows keyed by the same mid. Names are abbreviated (for example
J.Courier), so linking uses an exact initial+surname key, never fuzzy distance.

Safety policy:
- exact year + Wimbledon + tour
- exact two-player initial/surname pair
- exact winner orientation
- exact round when canonical round is known; otherwise both ranks must agree
- any source-internal point/match aggregate inconsistency quarantines the match
- ambiguous matches are rejected
- canonical write is performed only by the existing strict serve/return importer
- raw point observations are emitted to a private research sidecar only
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.offline_odds import norm_text

SOURCE = "klaassen_magnus_wimbledon_1992_1995"
SOURCE_DOI = "10.21942/uva.21983555"
SOURCE_VERSION = 3
LICENSE = "CC BY 4.0"

POINT_COLUMNS = (
    "pinm", "sinm", "gins", "ping", "servpinm",
    "set_i", "set_j", "game_i", "game_j", "point_i", "point_j",
    "tiebreak", "server", "win", "in1", "in2", "winin1", "winin2",
    "winon1", "winon2", "ace", "df", "imp", "newballs", "ageballs",
    "breakp", "servstarteds", "g1inm", "win_1", "win_10",
)


def _clean_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def initial_surname_key(value: object) -> str:
    text = _clean_text(value)
    parts = text.split()
    if len(parts) < 2:
        return ""
    first = parts[0][0]
    # Keep the complete surname tail. This is stricter for names such as
    # "Van Lottum" while still mapping "J.Courier" -> "Jim Courier".
    surname = " ".join(parts[1:])
    return f"{first} {surname}"


def _round_bucket(value: object) -> str:
    text = norm_text(value)
    numeric = None
    try:
        numeric = int(float(str(value).strip()))
    except (TypeError, ValueError):
        pass
    if numeric is not None:
        return {
            1: "r128",
            2: "r64",
            3: "r32",
            4: "r16",
            5: "qf",
            6: "sf",
            7: "f",
        }.get(numeric, "")
    aliases = {
        "1st round": "r128", "first round": "r128", "round of 128": "r128", "r128": "r128",
        "2nd round": "r64", "second round": "r64", "round of 64": "r64", "r64": "r64",
        "3rd round": "r32", "third round": "r32", "round of 32": "r32", "r32": "r32",
        "4th round": "r16", "fourth round": "r16", "round of 16": "r16", "r16": "r16",
        "quarterfinal": "qf", "quarterfinals": "qf", "quarter final": "qf", "qf": "qf",
        "semifinal": "sf", "semifinals": "sf", "semi final": "sf", "sf": "sf",
        "final": "f", "f": "f",
    }
    return aliases.get(text, "")


def _int(value: object) -> int | None:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _float(value: object) -> float | None:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _signature(match) -> dict[str, str]:
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


def _canonical_index(matches):
    index: dict[tuple[str, int, tuple[str, str]], list[Any]] = defaultdict(list)
    for match in matches:
        tour = str(match.tour or "").lower()
        if tour not in {"atp", "wta"}:
            continue
        year = int(match.scheduled_at.year)
        if year not in {1992, 1993, 1994, 1995}:
            continue
        if "wimbledon" not in norm_text(match.tournament):
            continue
        k1 = initial_surname_key(match.player1_name)
        k2 = initial_surname_key(match.player2_name)
        if not k1 or not k2 or k1 == k2:
            continue
        index[(tour, year, tuple(sorted((k1, k2))))].append(match)
    return index


def _group_match_rows(frame: pd.DataFrame):
    required = {
        "mid", "player", "round", "year", "name", "rank", "name_opp",
        "rank_opp", "T", "T2", "Tin1", "Tin2", "Twinin1", "Twinin2",
        "Twin", "Tace", "Tdf", "winnerofm",
    }
    missing = sorted(required - set(map(str, frame.columns)))
    if missing:
        raise ValueError(f"Missing match data columns: {missing}")
    for mid, group in frame.groupby("mid", sort=False, dropna=False):
        if pd.isna(mid):
            continue
        rows = {}
        for _, row in group.iterrows():
            side = str(row.get("player") or "").strip().upper()
            if side in {"I", "J"} and side not in rows:
                rows[side] = row
        yield str(mid), rows


def _point_internal_validation(
    rows: dict[str, pd.Series],
    points: pd.DataFrame,
) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if set(rows) != {"I", "J"}:
        return False, ["source_match_rows_not_IJ"]
    if points.empty:
        return False, ["no_point_rows"]

    for side, server_code in (("I", 1), ("J", 2)):
        match_row = rows[side]
        served = points[pd.to_numeric(points["server"], errors="coerce") == server_code]
        checks = {
            "T": len(served),
            "T2": int((pd.to_numeric(served["in1"], errors="coerce") == 0).sum()),
            "Tin1": int(pd.to_numeric(served["in1"], errors="coerce").fillna(0).sum()),
            "Tin2": int(pd.to_numeric(served["in2"], errors="coerce").fillna(0).sum()),
            "Twinin1": int(pd.to_numeric(served["winin1"], errors="coerce").fillna(0).sum()),
            "Twinin2": int(pd.to_numeric(served["winin2"], errors="coerce").fillna(0).sum()),
            "Twin": int(pd.to_numeric(served["win"], errors="coerce").fillna(0).sum()),
            "Tace": int(pd.to_numeric(served["ace"], errors="coerce").fillna(0).sum()),
            "Tdf": int(pd.to_numeric(served["df"], errors="coerce").fillna(0).sum()),
        }
        for field, actual in checks.items():
            expected = _int(match_row.get(field))
            if expected is None or expected != actual:
                issues.append(f"{side}:{field}:{expected}!={actual}")
    return not issues, issues


def _rank_agrees(source_rank: object, canonical_rank: object) -> bool | None:
    source = _int(source_rank)
    target = _int(canonical_rank)
    if source is None or target is None:
        return None
    return source == target


def _candidate_orientation(source_i: pd.Series, source_j: pd.Series, match):
    si = initial_surname_key(source_i.get("name"))
    sj = initial_surname_key(source_j.get("name"))
    p1 = initial_surname_key(match.player1_name)
    p2 = initial_surname_key(match.player2_name)
    if not all((si, sj, p1, p2)):
        return None
    if si == p1 and sj == p2:
        return "direct"
    if si == p2 and sj == p1:
        return "reversed"
    return None


def _winner_name(rows: dict[str, pd.Series]) -> str:
    winners = [
        str(row.get("name") or "")
        for row in rows.values()
        if _int(row.get("winnerofm")) == 1
    ]
    return winners[0] if len(winners) == 1 else ""


def _winner_canonical_name(match) -> str:
    if str(match.winner_id or "") == str(match.player1_id):
        return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id):
        return str(match.player2_name or "")
    return ""


def _resolve_source_match(
    rows: dict[str, pd.Series],
    candidates: list[Any],
) -> tuple[Any | None, str | None, list[dict[str, Any]]]:
    if set(rows) != {"I", "J"}:
        return None, None, []
    source_i, source_j = rows["I"], rows["J"]
    source_round = _round_bucket(source_i.get("round"))
    source_winner = initial_surname_key(_winner_name(rows))
    scored = []

    for match in candidates:
        orientation = _candidate_orientation(source_i, source_j, match)
        if orientation is None:
            continue
        target_winner = initial_surname_key(_winner_canonical_name(match))
        if not source_winner or source_winner != target_winner:
            continue

        canonical_round = _round_bucket(match.round_name)
        round_exact = bool(source_round and canonical_round and source_round == canonical_round)
        if source_round and canonical_round and source_round != canonical_round:
            continue

        if orientation == "direct":
            rank_i = _rank_agrees(source_i.get("rank"), match.player1_rank)
            rank_j = _rank_agrees(source_j.get("rank"), match.player2_rank)
        else:
            rank_i = _rank_agrees(source_i.get("rank"), match.player2_rank)
            rank_j = _rank_agrees(source_j.get("rank"), match.player1_rank)

        if rank_i is False or rank_j is False:
            continue
        both_rank_exact = rank_i is True and rank_j is True

        # If round provenance is unavailable in canonical data, require both
        # point-in-time ranks to match before accepting the candidate.
        if not round_exact and not both_rank_exact:
            continue

        evidence = ["year", "wimbledon", "initial_surname_pair", "winner"]
        if round_exact:
            evidence.append("round")
        if rank_i is True:
            evidence.append("rank_i")
        if rank_j is True:
            evidence.append("rank_j")
        scored.append({
            "match": match,
            "orientation": orientation,
            "evidence": evidence,
            "score": len(evidence),
        })

    if not scored:
        return None, None, []
    scored.sort(key=lambda item: item["score"], reverse=True)
    top_score = scored[0]["score"]
    top = [item for item in scored if item["score"] == top_score]
    if len(top) != 1:
        return None, None, scored
    chosen = top[0]
    return chosen["match"], chosen["orientation"], scored


def _rate(num: object, den: object) -> float | None:
    n, d = _float(num), _float(den)
    if n is None or d is None or d <= 0:
        return None
    result = n / d
    return result if 0 <= result <= 1 else None


def _aggregate_side(match_row: pd.Series, points: pd.DataFrame, server_code: int) -> dict[str, Any]:
    served = points[pd.to_numeric(points["server"], errors="coerce") == server_code]
    break_points = served[pd.to_numeric(served["breakp"], errors="coerce") == 1]
    bp_serve_win = None
    if len(break_points):
        bp_serve_win = float(pd.to_numeric(break_points["win"], errors="coerce").mean())
        if not math.isfinite(bp_serve_win):
            bp_serve_win = None

    service_win = _rate(match_row.get("Twin"), match_row.get("T"))
    return {
        "aces": _int(match_row.get("Tace")),
        "double_faults": _int(match_row.get("Tdf")),
        "first_serve_win": _rate(match_row.get("Twinin1"), match_row.get("Tin1")),
        "second_serve_win": _rate(match_row.get("Twinin2"), match_row.get("Tin2")),
        "service_points_won": service_win,
        "break_point_serve_win": bp_serve_win,
        "service_points": _int(match_row.get("T")),
        "first_serves_in": _int(match_row.get("Tin1")),
        "second_serves_in": _int(match_row.get("Tin2")),
        "break_points_faced": int(len(break_points)),
    }


def _incoming_stats(
    rows: dict[str, pd.Series],
    points: pd.DataFrame,
    orientation: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    i = _aggregate_side(rows["I"], points, 1)
    j = _aggregate_side(rows["J"], points, 2)

    if orientation == "direct":
        p1, p2 = i, j
    else:
        p1, p2 = j, i

    p1["return_points_won"] = (
        1.0 - p2["service_points_won"] if p2["service_points_won"] is not None else None
    )
    p2["return_points_won"] = (
        1.0 - p1["service_points_won"] if p1["service_points_won"] is not None else None
    )
    p1["break_point_return_win"] = (
        1.0 - p2["break_point_serve_win"] if p2["break_point_serve_win"] is not None else None
    )
    p2["break_point_return_win"] = (
        1.0 - p1["break_point_serve_win"] if p1["break_point_serve_win"] is not None else None
    )

    allowed = {
        "aces", "double_faults", "first_serve_win", "second_serve_win",
        "service_points_won", "return_points_won",
        "break_point_serve_win", "break_point_return_win",
    }
    incoming: dict[str, float] = {}
    for prefix, side in (("p1", p1), ("p2", p2)):
        for key in allowed:
            value = side.get(key)
            if value is None:
                continue
            incoming[f"{prefix}_{key}"] = float(value)

    detail = {"source_I": i, "source_J": j, "canonical_p1": p1, "canonical_p2": p2}
    return incoming, detail


def _json_scalar(value: object):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        number = float(value)
        if math.isfinite(number):
            return int(number) if number.is_integer() else number
    except Exception:
        pass
    return str(value)


def _point_tape(points: pd.DataFrame) -> list[dict[str, Any]]:
    ordered = points.sort_values(["pinm", "sinm", "gins", "ping"], kind="stable")
    tape = []
    for _, row in ordered.iterrows():
        tape.append({
            key: _json_scalar(row.get(key))
            for key in POINT_COLUMNS
            if key in row.index
        })
    return tape


def build_link(
    *,
    workbook: Path,
    history_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    matches, safety = sanitize_history_identities(load_partitions(history_dir))
    if safety.get("quarantined_rows"):
        raise RuntimeError("Canonical history identity quarantine is non-empty")
    index = _canonical_index(matches)

    out_dir.mkdir(parents=True, exist_ok=True)
    stage = []
    sidecar = []
    review = []
    counts = Counter()
    by_tour = Counter()
    by_year = Counter()

    for tour, match_sheet, point_sheet in (
        ("atp", "MatchData_Men", "PointData_Men"),
        ("wta", "MatchData_Women", "PointData_Women"),
    ):
        match_frame = pd.read_excel(workbook, sheet_name=match_sheet)
        point_frame = pd.read_excel(workbook, sheet_name=point_sheet)
        if "mid" not in point_frame.columns:
            raise ValueError(f"{point_sheet}: missing mid")
        point_groups = {str(mid): group for mid, group in point_frame.groupby("mid", sort=False)}

        for source_mid, rows in _group_match_rows(match_frame):
            counts["source_matches"] += 1
            by_tour[f"source_{tour}"] += 1
            if set(rows) != {"I", "J"}:
                counts["invalid_match_rows"] += 1
                review.append({"source_mid": source_mid, "reason": "invalid_match_rows"})
                continue

            source_i, source_j = rows["I"], rows["J"]
            year = _int(source_i.get("year"))
            if year not in {1992, 1993, 1994, 1995} or _int(source_j.get("year")) != year:
                counts["invalid_year"] += 1
                continue
            by_year[f"source_{year}"] += 1

            key_i = initial_surname_key(source_i.get("name"))
            key_j = initial_surname_key(source_j.get("name"))
            if not key_i or not key_j or key_i == key_j:
                counts["invalid_source_names"] += 1
                continue

            points = point_groups.get(source_mid)
            if points is None:
                counts["no_point_group"] += 1
                continue
            valid_points, issues = _point_internal_validation(rows, points)
            if not valid_points:
                counts["source_internal_conflict"] += 1
                review.append({
                    "source_mid": source_mid,
                    "reason": "source_internal_conflict",
                    "issues": issues[:20],
                })
                continue

            candidates = index.get((tour, year, tuple(sorted((key_i, key_j)))), [])
            match, orientation, scored = _resolve_source_match(rows, list(candidates))
            if match is None or orientation is None:
                reason = "unmatched" if not scored else "ambiguous"
                counts[reason] += 1
                review.append({
                    "source_mid": source_mid,
                    "reason": reason,
                    "year": year,
                    "tour": tour,
                    "players": [str(source_i.get("name")), str(source_j.get("name"))],
                    "candidate_match_ids": [
                        str(item["match"].match_id) for item in scored[:10]
                    ],
                })
                continue

            incoming, aggregates = _incoming_stats(rows, points, orientation)
            if not incoming:
                counts["no_usable_stats"] += 1
                continue

            source_round = _round_bucket(source_i.get("round"))
            canonical = _signature(match)
            stage_row = {
                "schema": 1,
                "match_id": str(match.match_id),
                "canonical": canonical,
                "incoming_stats": incoming,
                "import_ready": True,
                "source": {
                    "name": SOURCE,
                    "doi": SOURCE_DOI,
                    "version": SOURCE_VERSION,
                    "license": LICENSE,
                    "source_mid": source_mid,
                    "year": year,
                    "round": source_round,
                    "orientation": orientation,
                    "identity_evidence": (
                        "year+wimbledon+exact initial/surname pair+winner+"
                        "(round or both exact ranks)"
                    ),
                },
            }
            stage.append(stage_row)
            sidecar.append({
                "schema": 1,
                "match_id": str(match.match_id),
                "canonical": canonical,
                "source_mid": source_mid,
                "source": SOURCE,
                "doi": SOURCE_DOI,
                "version": SOURCE_VERSION,
                "license": LICENSE,
                "orientation": orientation,
                "source_players": {
                    "I": str(source_i.get("name") or ""),
                    "J": str(source_j.get("name") or ""),
                },
                "source_ranks": {
                    "I": _int(source_i.get("rank")),
                    "J": _int(source_j.get("rank")),
                },
                "aggregates": aggregates,
                "points": _point_tape(points),
                "feature_policy": (
                    "post_match_research_only; point outcomes update player state "
                    "only after the historical match completes"
                ),
            })
            counts["linked_matches"] += 1
            counts["linked_point_rows"] += int(len(points))
            by_tour[f"linked_{tour}"] += 1
            by_year[f"linked_{year}"] += 1

    match_ids = [row["match_id"] for row in stage]
    if len(match_ids) != len(set(match_ids)):
        raise RuntimeError("Duplicate canonical match IDs in Wimbledon stage")

    stage_path = out_dir / "serve-return-stage.jsonl"
    with stage_path.open("w", encoding="utf-8") as handle:
        for row in stage:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with gzip.open(out_dir / "wimbledon-1992-1995-pbp-sidecar.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in sidecar:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    with (out_dir / "review.jsonl").open("w", encoding="utf-8") as handle:
        for row in review:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "schema": 1,
        "status": "verified",
        "source": SOURCE,
        "doi": SOURCE_DOI,
        "version": SOURCE_VERSION,
        "license": LICENSE,
        "canonical_rows": len(matches),
        "counts": dict(counts),
        "by_tour": dict(by_tour),
        "by_year": dict(by_year),
        "identity_safety": safety,
        "production_mutated": False,
        "canonical_history_mutated": False,
        "model_promoted": False,
        "link_policy": (
            "fail_closed: exact year+Wimbledon+tour+initial/surname pair+winner; "
            "round exact when available, otherwise both point-in-time ranks exact; "
            "source point aggregates must reconcile exactly with match aggregates"
        ),
        "feature_policy": (
            "derived canonical serve/return stats are historical post-match state; "
            "raw point tape remains private sidecar; no same-match target leakage"
        ),
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    report = build_link(
        workbook=Path(args.workbook),
        history_dir=Path(args.history_dir),
        out_dir=Path(args.out_dir),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
