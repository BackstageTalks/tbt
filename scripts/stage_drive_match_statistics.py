"""Stage Drive tennis CSV match statistics in the exact TennisAPI statistics envelope.

READ-ONLY: generates candidates, NOT authorized CDB writes. No paid HTTP/API calls.
Source winner/loser become *synthetic* home/away for parser compatibility only;
the real provider/canonical event identity remains unverified. Preserve provenance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tbt.errors import ProviderError
from tbt.providers.statistics import parse_statistics

# The source uses winner/loser orientation. No source player ID is treated as
# the canonical CDB or TennisAPI player ID until independently cross-checked.
RATE_COLUMNS = (
    ("Service points won", "service_points_won", "service_points_total"),
    ("Return points won", "return_points_won", "return_points_total"),
    ("1st serve points won", "first_serve_points_won", "first_serve_points_total"),
    ("2nd serve points won", "second_serve_points_won", "second_serve_points_total"),
    ("first return points", "first_serve_return_won", "first_serve_return_total"),
    ("second return points", "second_serve_return_won", "second_serve_return_total"),
    ("Break points converted", "break_points_converted", "break_points_return_total"),
)
COUNT_COLUMNS = (
    ("Aces", "aces"),
    ("Double faults", "double_faults"),
)


def _nonnegative_int(value, name):
    if value is None or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid integer {name}") from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError(f"Invalid nonnegative integer {name}")
    return int(number)


def _counts(row, side, won_suffix, total_suffix):
    won = _nonnegative_int(row.get(f"{side}_{won_suffix}"), f"{side}_{won_suffix}")
    total = _nonnegative_int(row.get(f"{side}_{total_suffix}"), f"{side}_{total_suffix}")
    if (won is None) != (total is None):
        raise ValueError(f"Incomplete rate evidence {side}_{won_suffix}")
    if won is None:
        return None
    if not total or won > total:
        raise ValueError(f"Impossible numerator/denominator {side}_{won_suffix}")
    return won, total


def _cross_check(row):
    for serving, returning in (("winner", "loser"), ("loser", "winner")):
        own = _counts(row, serving, "service_points_won", "service_points_total")
        opp = _counts(row, returning, "return_points_won", "return_points_total")
        if own and opp and (own[1] != opp[1] or own[0] + opp[0] != own[1]):
            raise ValueError(f"Opposing serve/return totals disagree: {serving}")


def make_payload(row):
    """Use actual provider parser shapes, but NEVER impersonate a paid response."""
    _cross_check(row)
    items = []
    for name, won_suffix, total_suffix in RATE_COLUMNS:
        item = {"name": name}
        for side, prefix in (("winner", "home"), ("loser", "away")):
            counts = _counts(row, side, won_suffix, total_suffix)
            if counts is not None:
                item[f"{prefix}Value"], item[f"{prefix}Total"] = counts
        if len(item) > 1:
            items.append(item)
    for name, suffix in COUNT_COLUMNS:
        item = {"name": name}
        for side, prefix in (("winner", "home"), ("loser", "away")):
            count = _nonnegative_int(row.get(f"{side}_{suffix}"), f"{side}_{suffix}")
            if count is not None:
                item[f"{prefix}Value"] = count
        if len(item) > 1:
            items.append(item)
    if not items:
        raise ValueError("No supported observed match statistics")
    payload = {"statistics": [{"period": "ALL", "groups": [
        {"groupName": "Drive verified source values", "statisticsItems": items}
    ]}]}
    try:
        normalized = parse_statistics(payload, home_is_player1=True)
    except ProviderError as exc:
        raise ValueError(f"TennisAPI-compatible parser refused input: {exc}") from exc
    if not normalized:
        raise ValueError("No parseable statistics")
    return payload, normalized


def stage_row(row, *, file_sha256, source_file_id, line_number):
    payload, normalized = make_payload(row)
    source_ids = {
        "winner": str(row.get("winner_player_id") or "").strip() or None,
        "loser": str(row.get("loser_player_id") or "").strip() or None,
    }
    if source_ids["winner"] and source_ids["winner"] == source_ids["loser"]:
        raise ValueError("Self-match source player identity")
    # The 2017 match_stats CSV contains a source match_id but no canonical
    # player identities, so it must stay blocked from CDB publication.
    return {
        "schema": 1,
        "kind": "drive_statistics_rapidapi_compatible_stage",
        "import_ready": False,
        "identity_status": "canonical_match_and_both_player_identities_unverified",
        "source": {
            "kind": "google_drive_offline_csv",
            "file_id": source_file_id,
            "sha256": file_sha256,
            "csv_line": line_number,
            "source_match_id": str(row.get("match_id") or "").strip() or None,
            "source_player_ids": source_ids,
            "match_url_suffix": str(row.get("match_stats_url_suffix") or "").strip() or None,
        },
        "match_hints": {
            "tournament": str(row.get("tourney_name") or "").strip() or None,
            "tournament_date_hint": str(row.get("tourney_dates") or "").strip() or None,
            "round": str(row.get("tourney_round_name") or "").strip() or None,
            "winner_name": str(row.get("winner_name") or "").strip() or None,
            "loser_name": str(row.get("loser_name") or "").strip() or None,
            "score": str(row.get("match_score") or "").strip() or None,
        },
        "orientation": "synthetic_home_winner_away_loser_NOT_provider_home_away",
        "tennisapi_compatible_statistics": payload,
        "normalized_candidate_stats": normalized,
        "canonical_match_id": None,
        "provider_event_id": None,
        "provenance_policy": "offline_observed_post_match; verify licensing, canonical identity, current CDB cells, and writer lock before promotion",
    }


def _read_headers(header_path):
    lines = [line.strip() for line in Path(header_path).read_text(
        encoding="utf-8-sig").splitlines() if line.strip()]
    if len(lines) < 8 or len(lines) != len(set(lines)):
        raise ValueError("Invalid/duplicate source column titles")
    required = {"winner_service_points_won", "winner_service_points_total",
                "loser_service_points_won", "loser_service_points_total"}
    if not required.issubset(lines):
        raise ValueError("Source columns lack whole-match service rates")
    return lines


def run(input_path, header_path, out_dir, source_file_id):
    src, output = Path(input_path), Path(out_dir)
    if not source_file_id or "/" in source_file_id or " " in source_file_id:
        raise ValueError("Use the original Google Drive file ID, not a URL/name")
    headers = _read_headers(header_path)
    with src.open("rb") as file_handle:
        digest = hashlib.file_digest(file_handle, "sha256").hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    accepted = output / "stage.jsonl"
    rejected = output / "quarantine.jsonl"
    counts = Counter()
    with src.open("r", encoding="utf-8-sig", newline="") as source, \
            accepted.open("w", encoding="utf-8") as good, \
            rejected.open("w", encoding="utf-8") as bad:
        reader = csv.reader(source)
        for number, values in enumerate(reader, 1):
            if not values or (len(values) == 1 and not values[0].strip()):
                continue
            counts["rows_seen"] += 1
            try:
                if len(values) != len(headers):
                    raise ValueError(f"Column count {len(values)} != {len(headers)}")
                record = stage_row(dict(zip(headers, values)), file_sha256=digest,
                                   source_file_id=source_file_id, line_number=number)
                good.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                counts["staged_not_import_ready"] += 1
            except (ValueError, TypeError) as exc:
                bad.write(json.dumps({"source_file_id": source_file_id, "sha256": digest,
                                      "csv_line": number, "reason": str(exc)},
                                     sort_keys=True) + "\n")
                counts["quarantined"] += 1
    report = {"schema": 1, "source_file_id": source_file_id, "source_sha256": digest,
              "header_file": Path(header_path).name,
              "counts": dict(counts), "api_requests": 0, "cdb_writes": 0,
              "status": "SOURCE_STAGE_ONLY_CDB_DIFF_PENDING",
              "output_files": ["stage.jsonl", "quarantine.jsonl"],
              "promotion_requirements": [
                  "Source usage rights independently confirmed",
                  "Canonical match and BOTH players verified against pinned CDB",
                  "Check exact match date/round/score, not just tournament-week date",
                  "Recompute orientation against canonical p1/p2",
                  "Compare every staged field against current CDB; never overwrite conflicts",
                  "Acquire exclusive CDB writer lock and independently read back any promoted cells",
              ]}
    (output / "report.json").write_text(json.dumps(
        report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Downloaded original Drive CSV")
    parser.add_argument("--header-file", required=True,
                        help="One source column name per line; files are headerless")
    parser.add_argument("--source-file-id", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.header_file, args.out_dir,
                         args.source_file_id), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
