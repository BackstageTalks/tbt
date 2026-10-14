#!/usr/bin/env python3
"""Offline, chronological PRE-match Elo sidecar built from a verified CDB snapshot.

Uses the SAME BlinQ FeatureBuilder.update/snapshot state (not a second Elo formula).
Never edits the CDB, changes models, contacts tennis APIs or guesses player crosswalks.
Replays the entire canonical corpus on every weekly run, so late backfills and
historical corrections cannot silently leave stale downstream Elo values.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tbt.models.elo import elo_expected
from tbt.models.feature_builder import FeatureBuilder, stats_surface_key
from tbt.schemas import MatchRecord


COLUMNS = (
    "match_id", "tour", "scheduled_at", "player1_id", "player1_name",
    "player2_id", "player2_name", "winner_id", "surface", "tournament_level",
    "status",
)
OUTPUT_COLUMNS = (
    "match_id", "tour", "scheduled_at", "surface", "player1_id",
    "player1_name", "player2_id", "player2_name",
    "p1_elo_pre", "p2_elo_pre", "p1_surface_elo_pre", "p2_surface_elo_pre",
    "p1_yelo_pre", "p2_yelo_pre", "p1_matches_pre", "p2_matches_pre",
    "p1_surface_matches_pre", "p2_surface_matches_pre",
    "p1_yelo_matches_pre", "p2_yelo_matches_pre", "p1_expected_win_pre",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc(value) -> datetime:
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = value
    if not isinstance(dt, datetime):
        raise ValueError(f"Invalid CDB match date: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def read_year(path: Path):
    # Read only match identifiers and Elo-relevant context, not stats/odds/ranks.
    frame = pd.read_parquet(path, columns=list(COLUMNS), engine="pyarrow")
    if frame["match_id"].isna().any() or frame["scheduled_at"].isna().any():
        raise ValueError(f"Missing canonical identity/date in {path.name}")
    for record in frame.to_dict(orient="records"):
        dt = utc(record["scheduled_at"])
        p1, p2 = clean(record["player1_id"]), clean(record["player2_id"])
        if not p1 or not p2 or p1 == p2:
            raise ValueError(f"Invalid canonical player identities: {path.name}")
        yield MatchRecord(
            match_id=clean(record["match_id"]),
            tour=clean(record["tour"]).lower(),
            scheduled_at=dt,
            player1_id=p1,
            player1_name=clean(record["player1_name"]),
            player2_id=p2,
            player2_name=clean(record["player2_name"]),
            winner_id=clean(record["winner_id"]) or None,
            surface=clean(record["surface"]) or "unknown",
            tournament_level=clean(record["tournament_level"]),
            status=clean(record["status"]),
        )


def pre_match(match: MatchRecord, builder: FeatureBuilder) -> dict:
    # Read the exact state consumed by production before updating the day.
    p1 = builder._state(match, True)
    p2 = builder._state(match, False)
    surface = stats_surface_key(match.surface)
    y1, ny1 = builder._season_yelo_values(p1, match.scheduled_at)
    y2, ny2 = builder._season_yelo_values(p2, match.scheduled_at)
    result = {
        "match_id": match.match_id,
        "tour": match.tour,
        "scheduled_at": match.scheduled_at.isoformat(),
        "surface": surface,
        "player1_id": match.player1_id,
        "player1_name": match.player1_name,
        "player2_id": match.player2_id,
        "player2_name": match.player2_name,
        "p1_elo_pre": float(p1.overall_elo),
        "p2_elo_pre": float(p2.overall_elo),
        "p1_surface_elo_pre": float(p1.get_surface_elo(surface)),
        "p2_surface_elo_pre": float(p2.get_surface_elo(surface)),
        "p1_yelo_pre": float(y1),
        "p2_yelo_pre": float(y2),
        "p1_matches_pre": int(p1.matches),
        "p2_matches_pre": int(p2.matches),
        "p1_surface_matches_pre": int(p1.surface_matches.get(surface, 0)),
        "p2_surface_matches_pre": int(p2.surface_matches.get(surface, 0)),
        "p1_yelo_matches_pre": int(ny1),
        "p2_yelo_matches_pre": int(ny2),
        "p1_expected_win_pre": float(elo_expected(p1.overall_elo, p2.overall_elo)),
    }
    if not all(math.isfinite(result[k]) for k in (
        "p1_elo_pre", "p2_elo_pre", "p1_surface_elo_pre",
        "p2_surface_elo_pre", "p1_yelo_pre", "p2_yelo_pre",
        "p1_expected_win_pre",
    )):
        raise ValueError(f"Non-finite PRE Elo: {match.match_id}")
    return result


def replay_day(day_matches, builder, rows, last_names) -> None:
    # Whole UTC calendar day has frozen PRE values (same contract as training).
    for match in day_matches:
        rows.append(pre_match(match, builder))
        for player_id, name in (
            (match.player1_id, match.player1_name),
            (match.player2_id, match.player2_name),
        ):
            if name:
                last_names[builder.player_key(match.tour, player_id)] = name
    for match in day_matches:
        builder.update(match)


def persist_year(out: Path, year: int, rows: list[dict], parts: list[dict]) -> None:
    if not rows:
        return
    path = out / f"elo-history-{year}.parquet"
    pd.DataFrame(rows, columns=list(OUTPUT_COLUMNS)).to_parquet(
        path, index=False, compression="zstd", engine="pyarrow"
    )
    parts.append({
        "year": year, "filename": path.name,
        "rows": len(rows), "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    })


def build(root: Path, out: Path, *, app_sha: str, cutoff: datetime,
          min_input_matches: int = 995610) -> dict:
    source = root / "history_manifest.json"
    metadata = json.loads(source.read_text(encoding="utf-8"))
    years = sorted(int(y) for y in metadata["years"])
    if len(years) < 78:
        raise ValueError("CDB canonical year set has regressed")
    out.mkdir(parents=True, exist_ok=True)
    input_matches = completed_matches = 0
    source_names = {}
    builder = FeatureBuilder()
    seen = set()
    parts = []
    current_year = None
    year_rows = []
    day = None
    day_matches = []
    discarded = Counter()

    def finish_day():
        nonlocal day_matches
        if day_matches:
            replay_day(day_matches, builder, year_rows, source_names)
            day_matches = []

    for year in years:
        if current_year is not None:
            finish_day()
            persist_year(out, current_year, year_rows, parts)
            year_rows = []
        current_year = year
        path = root / f"history-{year}.parquet"
        if not path.is_file():
            raise FileNotFoundError(path.name)
        expected = metadata["years"][str(year)].get("sha256")
        if expected and sha256(path) != expected:
            raise ValueError(f"CDB history SHA mismatch: {path.name}")
        # A partition must be chronologically ordered before feeding the replay.
        matches = sorted(read_year(path), key=lambda r: (r.scheduled_at, r.match_id))
        for match in matches:
            input_matches += 1
            if not match.match_id or match.match_id in seen:
                raise ValueError(f"Missing/duplicated CDB match key: {match.match_id!r}")
            seen.add(match.match_id)
            if match.scheduled_at >= cutoff:
                discarded["at_or_after_cutoff"] += 1
                continue
            if not match.is_completed:
                discarded["no_verified_winner"] += 1
                continue
            utc_day = match.scheduled_at.date()
            if day is not None and utc_day != day:
                finish_day()
            day = utc_day
            day_matches.append(match)
            completed_matches += 1
        # finish_day() at year boundary; never expose POST values from same day.
    finish_day()
    if current_year is not None:
        persist_year(out, current_year, year_rows, parts)
    if input_matches < min_input_matches:
        raise ValueError(f"Canonical matches regressed: {input_matches} < {min_input_matches}")
    if sum(p["rows"] for p in parts) != completed_matches or not parts:
        raise ValueError("Missing Elo history rows or output partitions")

    current = out / "elo-current.csv"
    fieldnames = (
        "tour", "player_id", "player_name", "overall_elo", "overall_matches",
        "season_year", "season_yelo", "season_matches", "hard_elo",
        "clay_elo", "grass_elo", "hard_matches", "clay_matches",
        "grass_matches", "last_played_utc",
    )
    with current.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for key, state in sorted(builder.players.items()):
            tour, _, pid = key.partition(":")
            writer.writerow({
                "tour": tour, "player_id": pid,
                "player_name": source_names.get(key, ""),
                "overall_elo": state.overall_elo,
                "overall_matches": state.matches,
                "season_year": state.season_year,
                "season_yelo": state.season_yelo,
                "season_matches": state.season_matches,
                "hard_elo": state.get_surface_elo("hard"),
                "clay_elo": state.get_surface_elo("clay"),
                "grass_elo": state.get_surface_elo("grass"),
                "hard_matches": state.surface_matches.get("hard", 0),
                "clay_matches": state.surface_matches.get("clay", 0),
                "grass_matches": state.surface_matches.get("grass", 0),
                "last_played_utc": (
                    state.last_played.isoformat() if state.last_played else ""
                ),
            })
    report = {
        "schema": 1, "status": "verified_local",
        "algorithm": "Bl inQ FeatureBuilder v4".replace(" ", ""),
        "algorithm_source": "BackstageTalks/tbt/api/tbt/models/feature_builder.py",
        "app_sha": app_sha,
        "canonical_source_manifest_sha256": sha256(source),
        "cutoff_exclusive_utc": cutoff.isoformat(),
        "canonical_input_matches": input_matches,
        "eligible_completed_matches": completed_matches,
        "skipped_matches": dict(discarded),
        "current_player_states": len(builder.players),
        "year_partitions": parts,
        "current_csv_sha256": sha256(current),
        "tennis_provider_requests": 0,
        "canonical_cdb_writes": 0,
        "production_model_changed": False,
        "historical_policy": "all matches for same UTC date snapshotted before day results",
        "identity_policy": "canonical tour + player_id only, no invented crosswalk",
        "refresh_policy": "full replay from CDB every scheduled week; catches retroactive imports",
    }
    (out / "elo-manifest.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print("BLINQ_ELO_HISTORY_REPLAY_VERIFIED", json.dumps({
        k: report[k] for k in ("canonical_input_matches", "eligible_completed_matches",
                              "current_player_states", "canonical_source_manifest_sha256",
                              "canonical_cdb_writes")
    }, sort_keys=True), flush=True)
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cdb-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--app-sha", required=True)
    p.add_argument("--cutoff", default="")
    p.add_argument("--min-input-matches", type=int, default=995610)
    a = p.parse_args()
    cutoff = utc(a.cutoff) if a.cutoff else datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    build(a.cdb_dir, a.out, app_sha=a.app_sha, cutoff=cutoff,
          min_input_matches=a.min_input_matches)


if __name__ == "__main__":
    main()
