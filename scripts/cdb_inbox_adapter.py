#!/usr/bin/env python3
"""Convert bounded external tennis files to the existing Sackmann-style linker input.

SOURCE-ONLY: never writes CDB, resolves a canonical ID, or claims import readiness.
Unknown columns/formats and malformed rows are quarantined, never guessed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ROWS = 200_000
MAX_MEMBERS = 100
EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".parquet", ".zip"}
FIELDS = (
    "league", "tourney_date", "tourney_id", "match_num", "tourney_name",
    "winner_name", "loser_name", "surface", "round", "best_of",
    # Retain source identifiers as unverified provenance, never authoritative IDs.
    "source_winner_id", "source_loser_id",
    # The adapter, not an arbitrary input row, attests this date semantic.
    "source_date_kind",
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon",
    "w_bpSaved", "w_bpFaced", "l_ace", "l_df", "l_svpt",
    "l_1stIn", "l_1stWon", "l_2ndWon", "l_bpSaved", "l_bpFaced",
    # Explicit observed percentages, never fabricated service-point counts.
    "w_service_points_won_pct", "w_return_points_won_pct",
    "w_break_points_won_pct", "w_break_points_saved_pct",
    "l_service_points_won_pct", "l_return_points_won_pct",
    "l_break_points_won_pct", "l_break_points_saved_pct",
)
ALIASES = {
    "league": ("league", "tour", "circuit"),
    "tourney_date": ("tourney_date", "match_date", "event_date", "date"),
    "tourney_id": ("tourney_id", "tournament_id", "event_id"),
    "match_num": ("match_num", "match_id", "match_number"),
    "tourney_name": ("tourney_name", "tournament", "tournament_name", "event"),
    "winner_name": ("winner_name", "winner", "winning_player"),
    "loser_name": ("loser_name", "loser", "losing_player"),
    "surface": ("surface", "court_surface"),
    "round": ("round", "round_name"),
    "best_of": ("best_of", "bestof"),
    "source_winner_id": ("winner_id", "winner_player_id", "winning_player_id"),
    "source_loser_id": ("loser_id", "loser_player_id", "losing_player_id"),
}
STAT_FIELDS = FIELDS[13:]
for field in STAT_FIELDS:
    ALIASES[field] = (field,)
    if field.endswith("_ace"):
        ALIASES[field] = (field, field.replace("_ace", "_aces"))
    if field.endswith("_df"):
        ALIASES[field] = (field, field.replace("_df", "_double_faults"))
def key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())
def digest(blob):
    return hashlib.sha256(blob).hexdigest()
def iso_date(value):
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y%m%d")
    raw = str(value or "").strip()
    # Only known unambiguous calendar representations. Do not guess US/UK
    # slash dates or treat numeric Unix timestamps/Excel serials as match dates.
    if re.fullmatch(r"[0-9]{8}\.0+", raw):
        raw = raw.split(".", 1)[0]
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    return ""

def _utc_start(value):
    """Accept only a timestamp with a genuine explicit UTC offset."""
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", raw):
        return ""
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value.astimezone(timezone.utc).strftime("%Y%m%d")
    except ValueError:
        return ""


def _resolved_match_date(lookup):
    """Use explicit match timestamps, never silently prefer tournament start."""
    tournament_raw = str(lookup.get("tourneydate") or "").strip()
    tournament_day = iso_date(tournament_raw) if tournament_raw else ""
    match_raw = str(lookup.get("matchdate") or "").strip()
    match_day = iso_date(match_raw) if match_raw else ""
    if match_raw and not match_day:
        return "", "date_missing_or_invalid"
    start_raw = str(lookup.get("starttimeutc") or "").strip()
    start_day = _utc_start(start_raw) if start_raw else ""
    if start_raw and not start_day:
        return "", "start_time_utc_invalid"
    if match_day and start_day and match_day != start_day:
        return "", "match_date_start_time_conflict"
    day = start_day or match_day or tournament_day or iso_date(
        lookup.get("eventdate") or lookup.get("date")
    )
    if not day:
        return "", "date_missing_or_invalid"
    if (start_day or match_day) and tournament_raw:
        if not tournament_day:
            return "", "date_missing_or_invalid"
        span = (datetime.strptime(day, "%Y%m%d") -
                datetime.strptime(tournament_day, "%Y%m%d")).days
        if not 0 <= span <= 16:
            return "", "start_time_outside_tournament_window"
    return day, ""


def _valid_percent_pair(first, complementary):
    """No ratios from uncorroborated or contradictory 0+0 percentages."""
    try:
        first, complementary = float(first), float(complementary)
    except (ValueError, TypeError):
        return False
    return (math.isfinite(first) and math.isfinite(complementary)
            and 0 <= first <= 100 and 0 <= complementary <= 100
            and abs(first + complementary - 100) <= 1.01)


def _season_match(lookup):
    """Strict home/away event schema: source-only counts and paired percentages.

    Abbreviated names and source player IDs remain unverified; the canonical
    exact match linker, not this adapter, decides identity and import readiness.
    """
    required = ("homename", "awayname", "winnercode", "tourtypehuman",
                "datetimestamp", "status", "tournament")
    if any(not str(lookup.get(field) or "").strip() for field in required):
        return None, "season_schema_missing"
    tour = {"atptour": "atp", "wtatour": "wta"}.get(key(lookup["tourtypehuman"]))
    if not tour:
        return None, "tour_missing_or_unsupported"
    if (key(lookup["status"]) != "finished" or
            (lookup.get("statusextra") and key(lookup["statusextra"]) != "finished")):
        return None, "match_not_finished"
    code = str(lookup["winnercode"]).strip()
    if code not in {"1", "2"}:
        return None, "winner_unverified"
    home, away = str(lookup["homename"]).strip(), str(lookup["awayname"]).strip()
    if not home or not away or key(home) == key(away):
        return None, "players_missing_or_equal"
    home_sets, away_sets = str(lookup.get("homesetscore") or ""), str(lookup.get("awaysetscore") or "")
    if home_sets.isdigit() and away_sets.isdigit() and home_sets != away_sets:
        score_winner = "1" if int(home_sets) > int(away_sets) else "2"
        if score_winner != code:
            return None, "season_score_winner_conflict"
    timestamp = str(lookup["datetimestamp"]).strip()
    if not re.fullmatch(r"[1-9]\d{8,10}", timestamp):
        return None, "date_missing_or_invalid"
    try:
        day = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None, "date_missing_or_invalid"
    if not 2016 <= day.year <= 2026:
        return None, "date_missing_or_invalid"
    human = str(lookup.get("datehuman") or "").strip()
    if human:
        try:
            local_day = datetime.strptime(human, "%d %b %Y").date()
        except ValueError:
            return None, "date_missing_or_invalid"
        if abs((local_day - day).days) > 1:
            return None, "conflicting_match_dates"
    tournament = str(lookup["tournament"]).strip()
    # Only strip an explicit tour suffix. Tour remains independently required.
    tournament = re.sub(r"\s+" + tour + r"$", "", tournament, flags=re.I).strip()
    winner_side, loser_side = ("home", "away") if code == "1" else ("away", "home")
    row = {field: "" for field in FIELDS}
    row.update({
        "league": tour, "tourney_date": day.strftime("%Y%m%d"),
        "source_date_kind": "match_exact",
        "tourney_name": tournament,
        "match_num": str(lookup.get("matchid") or "").strip(),
        "winner_name": home if code == "1" else away,
        "loser_name": away if code == "1" else home,
        "source_winner_id": str(lookup.get(winner_side + "id") or "").strip(),
        "source_loser_id": str(lookup.get(loser_side + "id") or "").strip(),
        "surface": str(lookup.get("surface") or "").strip(),
        "round": str(lookup.get("round") or "").strip(),
    })
    for label, side in (("w", winner_side), ("l", loser_side)):
        for source_field, target in (("aces", "ace"), ("doublefaults", "df")):
            count = str(lookup.get(side + source_field) or "").strip()
            if re.fullmatch(r"(?:0|[1-9]\d{0,3})", count):
                row[f"{label}_{target}"] = count
    # The same point is a service win for one player and a return loss
    # for their opponent. Enforce this before retaining either percentage.
    for first, second, first_stat, second_stat in (
        ("servicepointswonperc", "returnpointswonperc",
         "service_points_won_pct", "return_points_won_pct"),
        ("breakpointssavedperc", "breakpointswonperc",
         "break_points_saved_pct", "break_points_won_pct"),
    ):
        for own, other in (("home", "away"), ("away", "home")):
            a, b = lookup.get(own + first), lookup.get(other + second)
            if _valid_percent_pair(a, b):
                own_label = "w" if own == winner_side else "l"
                other_label = "w" if other == winner_side else "l"
                row[f"{own_label}_{first_stat}"] = str(a).strip()
                row[f"{other_label}_{second_stat}"] = str(b).strip()
    if not any(row[field] for field in STAT_FIELDS):
        return None, "no_supported_serve_return_stats"
    return row, ""

def tour_from_filename(name):
    lowered = Path(name).name.lower()
    matches = [x for x in ("atp", "wta") if re.search(r"(^|[^a-z])" + x + r"([^a-z]|$)", lowered)]
    return matches[0] if len(matches) == 1 else ""


def tour_from_source_path(path):
    """Only an unambiguous ATP/WTA *folder*, not arbitrary words, gives a hint.

    The hint is SOURCE-ONLY. The linker still requires independent exact
    canonical match/date/winner/tournament and round-or-surface evidence.
    """
    folders = [key(part) for part in str(path or "").split("/")[:-1]]
    tours = {part for part in folders if part in {"atp", "wta"}}
    return next(iter(tours)) if len(tours) == 1 else ""


def _drive_source_hints(manifest_path: Path | None, input_dir: Path):
    """Bind original Drive path to its exact downloaded bytes and local file."""
    if manifest_path is None:
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != 2
            or data.get("state") != "DRIVE_SOURCE_FETCH_ONLY"
            or data.get("production_mutated") is not False
            or not isinstance(data.get("files"), list)):
        raise ValueError("Untrusted Drive source provenance manifest")
    hints = {}
    for item in data["files"]:
        if not isinstance(item, dict):
            raise ValueError("Malformed Drive manifest entry")
        if item.get("status") != "fetched":
            continue
        raw_path = item.get("local_file")
        source_sha = item.get("sha256")
        source_path = item.get("source_path") or ""
        if (not isinstance(raw_path, str)
                or not isinstance(source_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
                or not isinstance(source_path, str)):
            raise ValueError("Invalid fetched Drive source provenance")
        local = Path(raw_path).resolve()
        if local.parent != input_dir.resolve() or str(local) in hints:
            raise ValueError("Drive manifest local file boundary or duplicate")
        if source_path and (not source_path.startswith("/")
                            or ".." in source_path.split("/")):
            raise ValueError("Invalid original Drive source path")
        hints[str(local)] = (source_sha, source_path)
    return hints


# Pin the one manually reviewed TML ATP 2026 upload by exact source bytes
# AND its Drive provenance path. No generic year-only filename inference.
# This only recovers a SOURCE-ONLY tour hint; canonical identity remains
# exclusively with the exact offline linker.
TML_ATP_2026_SOURCE_SHA = "8e9b756d1874e9e7866796b797273dd3b791d89eeb6b52aa6ee961a2c4c82c01"
TML_ATP_2026_SOURCE_SUFFIX = "/Sackmann/TML/TML/2026.csv"
TML_ATP_SOURCE_ROOT = "/DIL_REBUILD_CDB_CANONICAL_20261023/Sackmann/TML/TML"
# Exact downloaded source checksums. Never infer ATP from bare YYYY.csv.
TML_ATP_SOURCE_SHAS = {
    2016: "28a106544a50184c742263eed43a49ca725be735cbf640143c51ab32e40e8588",
    2017: "b55f12e9bf5220b694cd8954f65027f1b7e649ce4977da0316a1a3f4f2f20ea4",
    2018: "5abc0e80e83ddab9f04f682b6e72fa062ad11d523c88f3c105f690a555bacc4a",
    2019: "6821d93e92de9110b365cd3b4f8d30138c261bcf679de4a5ccaff6917c33335e",
    2020: "3c97228abeede853db0139e4b49699aecbadafd2e7000acaaf9a449d38da202d",
    2021: "80d570be31d778b143eb58380258243785bf3fcb18db144b42704bc6c56d941b",
    2022: "d70036c6ee6c27dd3deda6e6c9ccd500b66e6e78106fb00794cb277e37353357",
    2023: "9faaf53186ef908b3322d521a8dd2a717401167c0e400a99e1efddb23e13600f",
    2024: "db27fb184b62bc1716ecc84c5a8365088e34e8e9a0101a59782ec7907f6e2de8",
    2025: "a00f5f991b4949c2c6867637ac02a8c44b9058780da67aba8600e9140002f8d3",
    2026: "8e9b756d1874e9e7866796b797273dd3b791d89eeb6b52aa6ee961a2c4c82c01",
}
# From independent TML-versus-BAL/123 source-only reconciliation:
# line 64 lacks loser source ID; line 121 is W/O with conflicting counts.
# Neither can become a CDB candidate even when the SHA-pinned tour is known.
# Exactly matched TML 2025 vs BAL ATP 2025 by winner, loser, event,
# round, surface, source tournament start + 0..16 days, and final score.
# Same match but 653 unequal observed fields in 112 source rows.
# This is a SHA-bound conflict review, NOT evidence that BAL is canonical.
# TML SHA: a00f5f991b4949c2c6867637ac02a8c44b9058780da67aba8600e9140002f8d3
# BAL SHA: 46f5c8b1cc6ee1706dff0f029b8d9dfdaea4613ad2db82cbe7ad6e83cefbaa55
# Ordinals are 1-based CSV record indices, NOT physical text line numbers.
TML_ATP_2025_CROSS_SOURCE_CONFLICT_ORDINALS = frozenset({
    635, 2194, 2195, 2196, 2197, 2198, 2199, 2200, 2201, 2202, 2203, 2204, 2205, 2206,
    2207, 2208, 2209, 2210, 2211, 2212, 2213, 2214, 2215, 2216, 2217, 2218, 2219, 2220,
    2221, 2222, 2223, 2224, 2225, 2226, 2227, 2228, 2229, 2230, 2231, 2232, 2233, 2234,
    2235, 2236, 2237, 2240, 2249, 2255, 2256, 2257, 2258, 2260, 2261, 2262, 2263, 2264,
    2265, 2266, 2267, 2268, 2269, 2270, 2271, 2273, 2274, 2275, 2276, 2277, 2278, 2279,
    2280, 2281, 2283, 2284, 2285, 2286, 2287, 2288, 2289, 2290, 2291, 2292, 2294, 2295,
    2296, 2297, 2298, 2299, 2300, 2301, 2302, 2303, 2304, 2305, 2306, 2307, 2308, 2309,
    2316, 2317, 2319, 2320, 2466, 2527, 2540, 2548, 2733, 2772, 2777, 2788, 2815, 2825,
})


TML_ATP_2026_QUARANTINE = frozenset({
    ("2026-336", "19"), ("2026-8998", "17"),
    ("2026-339", "18"), ("2026-336", "23"),
})


def tour_from_pinned_tml(sha, path):
    if not isinstance(path, str):
        return ""
    match = re.fullmatch(re.escape(TML_ATP_SOURCE_ROOT) + r"/(20(?:1[6-9]|2[0-6]))\.csv", path)
    if not match:
        return ""
    return "atp" if TML_ATP_SOURCE_SHAS.get(int(match.group(1))) == sha else ""


def _pinned_tml_safety_reason(raw):
    """Only match-level finished native records with coherent observed counts."""
    if not isinstance(raw, dict):
        return "tml_invalid_source_row"
    ids = [str(raw.get(k) or "").strip() for k in ("winner_id", "loser_id")]
    if not all(ids) or ids[0] == ids[1]:
        return "tml_native_identity_missing_or_equal"
    score = str(raw.get("score") or "").strip()
    if not score or re.search(r"\b(?:W/O|WO|RET|ABD|DEF|walkover)\b", score, re.I):
        return "tml_noncompleted_or_missing_score"
    # The existing native stage validates internal consistency; same quality
    # gate here prevents generic normalization from rescuing invalid totals.
    from cdb_native_sackmann_stage import _quality
    if _quality(raw) not in {"COMPLETE_BASIC_SERVE_RETURN", "VALID_PARTIAL_SERVE_OR_BP"}:
        return "tml_invalid_or_missing_stat_counts"
    return ""


def normalize(raw, filename, index, *, source_tour=""):
    if not isinstance(raw, dict):
        return None, "not_object"
    lookup = {key(k): v for k, v in raw.items() if k is not None}
    if "homename" in lookup or "awayname" in lookup:
        row, reason = _season_match(lookup)
        if not reason and source_tour and row["league"] != source_tour:
            return None, "tour_provenance_conflict"
        return row, reason
    row = {}
    for target, aliases in ALIASES.items():
        value = next((lookup[key(alias)] for alias in aliases if key(alias) in lookup), "")
        row[target] = "" if value is None else str(value).strip()
    row["tourney_date"], date_error = _resolved_match_date(lookup)
    if date_error:
        return None, date_error
    # A native tournament start is not an observed match date. The exact
    # provenance is derived only from validated UTC start/match_date input.
    # Never trust a caller-supplied source_date_kind field.
    row["source_date_kind"] = (
        "match_exact" if (str(lookup.get("starttimeutc") or "").strip()
                          or str(lookup.get("matchdate") or "").strip())
        else "tournament_start"
    )
    named_tour = tour_from_filename(filename)
    explicit_tour = row["league"].lower()
    if source_tour and (explicit_tour and explicit_tour != source_tour
                        or named_tour and named_tour != source_tour):
        return None, "tour_provenance_conflict"
    row["league"] = (explicit_tour or named_tour or source_tour).lower()
    if row["league"] not in {"atp", "wta"}:
        return None, "tour_missing_or_unsupported"
    if not row["tourney_date"]:
        return None, "date_missing_or_invalid"
    if not row["winner_name"] or not row["loser_name"] or key(row["winner_name"]) == key(row["loser_name"]):
        return None, "players_missing_or_equal"
    if not row["tourney_name"]:
        return None, "tournament_missing"
    if not any(row[f] for f in STAT_FIELDS):
        return None, "no_supported_serve_return_stats"
    row["match_num"] = row["match_num"] or str(index)
    return row, ""
def _explicit_json_match_table(rows, columns=None):
    """Decode only explicitly headed match-level JSON tables, never inferred arrays.

    Unlabeled sequences and per-player leaderboards remain source-only review.
    The ordinary match/date/stat and CDB identity gates still run afterwards.
    """
    if not isinstance(rows, list) or not rows or isinstance(rows[0], dict):
        return rows
    values = rows if columns is not None else rows[1:]
    headers = columns if columns is not None else rows[0]
    if not isinstance(headers, list) or not headers or not all(
        isinstance(h, str) and h.strip() for h in headers
    ):
        return rows
    keys = [key(h) for h in headers]
    present = set(keys)
    def has(field):
        return any(key(alias) in present for alias in ALIASES[field])
    if (not all(has(field) for field in (
            "tourney_date", "tourney_name", "winner_name", "loser_name"))
            or not any(has(field) for field in STAT_FIELDS)):
        return rows
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate normalized JSON table headers")
    if any(not isinstance(row, list) or len(row) != len(headers)
           or any(isinstance(cell, (list, dict)) for cell in row)
           for row in values):
        raise ValueError("Ragged or nested explicit JSON match rows")
    return [dict(zip(headers, row)) for row in values]


def read_rows(blob, name):
    suffix = Path(name).suffix.lower()
    if suffix in {".csv", ".tsv"}:
        sample = blob.decode("utf-8-sig")
        delimiter = "\t" if suffix == ".tsv" else ","
        return csv.DictReader(io.StringIO(sample, newline=""), delimiter=delimiter)
    if suffix == ".jsonl":
        data = [json.loads(line) for line in blob.decode("utf-8-sig").splitlines() if line.strip()]
        return _explicit_json_match_table(data)
    if suffix == ".json":
        data = json.loads(blob.decode("utf-8-sig"))
        columns = None
        if isinstance(data, dict):
            columns = data.get("columns")
            data = data.get("matches", data.get("rows"))
        if not isinstance(data, list):
            raise ValueError("JSON must contain a list or matches/rows list")
        return _explicit_json_match_table(data, columns)
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        try:
            if len(wb.worksheets) != 1:
                raise ValueError("Excel must contain exactly one data sheet")
            it = wb.worksheets[0].iter_rows(values_only=True)
            header = next(it, None)
            if not header:
                return []
            keys = [str(v or "") for v in header]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate Excel headers")
            return [dict(zip(keys, row)) for row in it]
        finally:
            wb.close()
    if suffix == ".parquet":
        import pandas as pd
        return pd.read_parquet(io.BytesIO(blob)).to_dict("records")
    raise ValueError("Unsupported table format")
def pieces(name, blob):
    if Path(name).suffix.lower() != ".zip":
        yield name, blob
        return
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = [x for x in archive.infolist() if not x.is_dir()]
        if len(members) > MAX_MEMBERS:
            raise ValueError("Archive has too many members")
        if sum(x.file_size for x in members) > MAX_FILE_BYTES:
            raise ValueError("Archive exceeds uncompressed size limit")
        for info in members:
            suffix = Path(info.filename).suffix.lower()
            if suffix not in EXTENSIONS - {".zip"}:
                continue
            if info.file_size > MAX_MEMBER_BYTES or info.flag_bits & 1:
                raise ValueError("Oversized or encrypted ZIP member")
            yield info.filename, archive.read(info)
def run(input_dir: Path, out_dir: Path, max_files: int = 100,
        drive_manifest_path: Path | None = None):
    source_hints = _drive_source_hints(drive_manifest_path, input_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized = out_dir / "normalized"
    normalized.mkdir(exist_ok=True)
    files = sorted(p for p in input_dir.iterdir() if p.is_file())
    if len(files) > max_files:
        raise ValueError("Unbounded inbox: file count exceeds configured limit")
    counts = Counter()
    review = []
    outputs = []
    source_diagnostics = []
    hashes = set()
    for path in files:
        blob = path.read_bytes()
        sha = digest(blob)
        original_sha, original_path = source_hints.get(str(path.resolve()), ("", ""))
        if drive_manifest_path is not None and (not original_sha or original_sha != sha):
            raise ValueError("Downloaded source does not match Drive provenance SHA")
        if sha in hashes:
            counts["duplicate_source_files"] += 1
            continue
        hashes.add(sha)
        if len(blob) > MAX_FILE_BYTES or path.suffix.lower() not in EXTENSIONS:
            counts["unsupported_or_oversized_files"] += 1
            review.append({"sha256": sha, "reason": "unsupported_or_oversized"})
            continue
        try:
            components = list(pieces(path.name, blob))
        except (ValueError, zipfile.BadZipFile, RuntimeError):
            counts["invalid_archives"] += 1
            review.append({"sha256": sha, "reason": "invalid_archive"})
            continue
        for part_no, (member_name, part) in enumerate(components):
            # ZIPs may mix tours: do not project an archive's folder onto
            # unknown member rows. Only member names/explicit columns apply.
            folder_tour = ((tour_from_source_path(original_path)
                            or tour_from_pinned_tml(original_sha, original_path))
                           if path.suffix.lower() != ".zip" else "")
            if len(part) > MAX_MEMBER_BYTES:
                counts["unsupported_or_oversized_files"] += 1
                continue
            counts["source_tables"] += 1
            try:
                rows = read_rows(part, member_name)
                tables = {"atp": [], "wta": []}
                table_rejections = Counter()
                non_object_types = Counter()
                table_seen = 0
                is_pinned_tml = (
                    path.suffix.lower() != ".zip"
                    and tour_from_pinned_tml(original_sha, original_path) == "atp"
                )
                for index, raw in enumerate(rows, 1):
                    if index > MAX_ROWS:
                        raise ValueError("Table exceeds row limit")
                    counts["raw_rows"] += 1
                    table_seen += 1
                    if not isinstance(raw, dict):
                        non_object_types[type(raw).__name__] += 1
                    if is_pinned_tml:
                        tml_reason = _pinned_tml_safety_reason(raw)
                        if (not tml_reason and
                                (str(raw.get("tourney_id") or ""),
                                 str(raw.get("match_num") or "")) in TML_ATP_2026_QUARANTINE
                                and original_sha == TML_ATP_2026_SOURCE_SHA):
                            tml_reason = "tml_cross_source_review_quarantine"
                        if (not tml_reason
                                and original_sha == TML_ATP_SOURCE_SHAS[2025]
                                and index in TML_ATP_2025_CROSS_SOURCE_CONFLICT_ORDINALS):
                            tml_reason = "tml_cross_source_stat_disagreement"
                        if tml_reason:
                            counts["rejected_rows"] += 1
                            counts["reason_" + tml_reason] += 1
                            table_rejections[tml_reason] += 1
                            continue
                    row, reason = normalize(raw, member_name, index,
                                            source_tour=folder_tour)
                    if reason:
                        counts["rejected_rows"] += 1
                        counts["reason_" + reason] += 1
                        table_rejections[reason] += 1
                        continue
                    tables[row["league"]].append(row)
                    if folder_tour and not tour_from_filename(member_name) and isinstance(raw, dict):
                        row_values = {key(x): str(value or "").strip()
                                      for x, value in raw.items() if x is not None}
                        if not any(row_values.get(name) for name in
                                   ("league", "tour", "circuit", "tourtypehuman")):
                            counts["rows_rescued_by_sha_verified_drive_folder_tour"] += 1
                for tour, accepted in tables.items():
                    if not accepted:
                        continue
                    dest = normalized / (tour + "_" + sha[:16] + "_" + str(part_no) + ".csv")
                    with dest.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=FIELDS)
                        writer.writeheader()
                        writer.writerows(accepted)
                    outputs.append({"path": str(dest), "tour": tour, "rows": len(accepted),
                                    "source_sha256": sha, "member_sha256": digest(part)})
                    counts["normalized_rows"] += len(accepted)
                source_diagnostics.append({
                    "source_sha256": sha, "member_sha256": digest(part),
                    "source_path": original_path or path.name,
                    "member_name": member_name,
                    "non_object_row_types": dict(sorted(non_object_types.items())),
                    "raw_rows": table_seen,
                    "normalized_rows": table_seen - sum(table_rejections.values()),
                    "rejected_by_reason": dict(sorted(table_rejections.items())),
                    "state": "SOURCE_ONLY", "production_mutated": False,
                })
            except (ValueError, KeyError, UnicodeError, csv.Error, ImportError, TypeError) as exc:
                counts["review_tables"] += 1
                review.append({"sha256": sha, "member_sha256": digest(part),
                               "reason": type(exc).__name__})
    report = {"schema": 1, "state": "SOURCE_ONLY", "production_mutated": False,
              "api_requests": 0, "counts": dict(counts),
              "normalized": outputs, "review": review,
        "source_diagnostics": source_diagnostics}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--max-files", type=int, default=100)
    parser.add_argument("--drive-manifest", type=Path,
                        help="SHA-verified same-run Drive source provenance")
    args = parser.parse_args()
    report = run(args.input_dir, args.out_dir, args.max_files, args.drive_manifest)
    print(json.dumps({"state": report["state"], "counts": report["counts"],
                      "normalized_files": len(report["normalized"])}))
if __name__ == "__main__":
    main()
