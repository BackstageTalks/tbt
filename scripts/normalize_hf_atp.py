"""Read-only, fail-closed normalization of the Yahya ATP Tour mirror.

Output is a *quarantined source sidecar*, not an import_offline_* stage.
Neither this utility nor its output has authority to write canonical history.
All existing canonical cells, identities, and model inputs remain unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

SOURCE = "Yahya777777/ATP-Tennis-Matches-Dataset-2015-to-2025"
URL = re.compile(r"^/en/scores/match-stats/archive/(20\d\d)/(\d+)/([a-z0-9]+)$")
FRACTION = re.compile(r"^\s*(\d{1,3})%\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)\s*$")
COUNT_NAMES = {"Aces": "aces", "Double_Faults": "double_faults"}
RATIO_NAMES = {
    "1st_Serve_Points_Won": "first_serve_win",
    "2nd_Serve_Points_Won": "second_serve_win",
    "Service_Points_Won": "service_points_won",
    "Return_Points_Won": "return_points_won",
    "Break_Points_Saved": "break_point_serve_win",
    "Break_Points_Converted": "break_point_return_win",
}
MAX_MEMBER_BYTES = 8_000_000
MAX_ARCHIVE_BYTES = 180_000_000


def normalize_url(value: str) -> tuple[str, int] | None:
    parsed = urlsplit((value or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in {"www.atptour.com", "atptour.com"} or parsed.query or parsed.fragment or parsed.username:
        return None
    match = URL.fullmatch(parsed.path.rstrip("/").lower())
    if not match:
        return None
    return f"https://www.atptour.com{parsed.path.rstrip('/').lower()}", int(match.group(1))


def fraction(value: str) -> float | None:
    match = FRACTION.fullmatch(str(value or ""))
    if not match:
        return None
    pct, n, d = map(int, match.groups())
    if d <= 0 or n > d or abs(100 * n / d - pct) > 1.0:
        return None
    return n / d


def stats_for_side(row: dict, side: str) -> tuple[dict[str, float], list[str]]:
    result = {}
    rejected = []
    for source, target in COUNT_NAMES.items():
        raw = str(row.get(f"match_{source}_{side}") or "").strip()
        if not raw:
            continue
        if not re.fullmatch(r"\d+", raw) or int(raw) > 200:
            rejected.append(source)
        else:
            result[target] = float(int(raw))
    for source, target in RATIO_NAMES.items():
        raw = str(row.get(f"match_{source}_{side}") or "").strip()
        if not raw:
            continue
        # ATP reports 0%(0/0) where no break-point chance occurred.
        # This is missing data, not a failed rate or a reason to drop
        # the match's otherwise valid ace/serve/return observations.
        match = FRACTION.fullmatch(raw)
        if match and tuple(map(int, match.groups())) == (0, 0, 0):
            continue
        rate = fraction(raw)
        if rate is None:
            rejected.append(source)
        else:
            result[target] = rate
    # Explicitly do NOT import YTD, rating, service_games_played,
    # return_games_played, or winner-first/order as predictive features.
    return result, rejected


def _source_rows(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            total = 0
            for member in sorted(archive.infolist(), key=lambda x: x.filename):
                if member.is_dir() or not member.filename.lower().endswith(".csv"):
                    continue
                pp = PurePosixPath(member.filename)
                if pp.is_absolute() or ".." in pp.parts:
                    raise ValueError("Unsafe ZIP member path")
                total += member.file_size
                if member.file_size > MAX_MEMBER_BYTES or total > MAX_ARCHIVE_BYTES:
                    raise ValueError("Unbounded CSV source archive")
                with archive.open(member) as stream:
                    payload = stream.read(MAX_MEMBER_BYTES + 1)
                if len(payload) != member.file_size:
                    raise ValueError("Truncated or oversized ZIP member")
                yield member.filename, payload
    elif path.suffix.lower() == ".csv":
        if path.stat().st_size > MAX_MEMBER_BYTES:
            raise ValueError("Oversized CSV input")
        yield path.name, path.read_bytes()
    else:
        raise ValueError("Provide a .zip or .csv source")


def prepare(path: Path, out: Path) -> dict:
    """Normalize and quarantine source rows. Never mark CDB import-ready."""
    counts: Counter = Counter()
    by_url: dict[str, dict] = {}
    conflicts: set[str] = set()
    seen_files: set[str] = set()
    for name, raw in _source_rows(path):
        counts["csv_members"] += 1
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_files:
            counts["duplicate_csv_members"] += 1
            continue
        seen_files.add(digest)
        try:
            decoded = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded, newline=""))
            if not reader.fieldnames or not {"player1", "player2", "winner", "stats_url"}.issubset(reader.fieldnames):
                counts["invalid_csv_schema"] += 1
                continue
            for lineno, row in enumerate(reader, start=2):
                counts["rows_seen"] += 1
                if None in row:
                    counts["malformed_rows"] += 1
                    continue
                ref = normalize_url(row.get("stats_url") or "")
                if not ref:
                    counts["missing_or_invalid_stat_url"] += 1
                    continue
                url, year = ref
                p1, p2, winner = (str(row.get(x) or "").strip() for x in ("player1", "player2", "winner"))
                if not p1 or not p2 or p1.casefold() == p2.casefold() or winner.casefold() not in {p1.casefold(), p2.casefold()}:
                    counts["invalid_player_identity"] += 1
                    continue
                s1, bad1 = stats_for_side(row, "p1")
                s2, bad2 = stats_for_side(row, "p2")
                if bad1 or bad2:
                    counts["invalid_stat_rows"] += 1
                    continue
                if not s1 or not s2:
                    counts["no_two_sided_stats"] += 1
                    continue
                # Coupled service/return rates must agree to rounded fractions.
                a, b = s1.get("service_points_won"), s2.get("return_points_won")
                c, d = s2.get("service_points_won"), s1.get("return_points_won")
                if any(x is not None and y is not None and abs(x + y - 1) > 0.012 for x, y in ((a, b), (c, d))):
                    counts["cross_side_conflicts"] += 1
                    continue
                record = {
                    "schema": 1, "dataset": SOURCE, "source_url": url,
                    "year": year, "player1": p1, "player2": p2, "winner": winner,
                    "round": str(row.get("round") or "").strip(),
                    "stats_p1": s1, "stats_p2": s2,
                    "original_member": name, "member_sha256": digest, "line": lineno,
                    "identity_verified": False, "rights_verified": False,
                    "import_ready": False, "quarantine_reason": "missing_independent_canonical_crosswalk_and_upstream_rights",
                }
                old = by_url.get(url)
                if old is not None:
                    signature = ("player1", "player2", "winner", "round", "stats_p1", "stats_p2")
                    if any(old[k] != record[k] for k in signature):
                        conflicts.add(url)
                        counts["conflicting_duplicate_urls"] += 1
                    else:
                        counts["duplicate_stat_urls"] += 1
                else:
                    by_url[url] = record
        except UnicodeDecodeError:
            counts["invalid_encoding_members"] += 1
    for url in conflicts:
        by_url.pop(url, None)
    out.mkdir(parents=True, exist_ok=True)
    staged = sorted(by_url.values(), key=lambda x: x["source_url"])
    with (out / "quarantined-observations.jsonl").open("w", encoding="utf-8") as stream:
        for record in staged:
            stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    counts["quarantined_observations"] = len(staged)
    counts["quarantined_candidate_cells"] = sum(len(x["stats_p1"]) + len(x["stats_p2"]) for x in staged)
    report = {
        "schema": 1, "status": "QUARANTINED_SOURCE_ONLY",
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "dataset": SOURCE, "source_license_card": "GPL-3.0 (mirror only; underlying ATP rights not verified)",
        "canonical_matches_verified": 0, "writer_approved_fields": 0, "cdb_values_written": 0,
        "counts": dict(sorted(counts.items())),
        "excluded_semantics": ["ytd_*", "match_*Rating*", "match_*Games_Played*", "winner_as_prematch_feature"],
        "next_required": ["original ATP data reuse rights", "independent ATP URL to canonical match/player-ID crosswalk", "fresh canonical NULL field-by-field check", "writer lock and immutable backup", "full remote readback"],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Source ZIP of per-tournament CSVs, or one CSV")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
