#!/usr/bin/env python3
"""Fail-closed source classification for wta.csv historical feature columns.

The file contains current match metadata (_CUR) and distinct player history
blocks (_1, _2, _L5, _A). It does NOT contain verified current-match serve/
return observations. No canonical match ID or CDB writer is used here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

MAX_BYTES = 4 * 1024**3
MAX_ROWS = 8_000_000
SOURCE_FIELDS = {"ID", "RID_CUR", "GameD", "TName", "Name_1", "Name_2",
                 "GRes_CUR_1", "RID_1", "RID_2", "GRes_1", "GRes_2",
                 "Serve1st_1", "Serve1st_2", "Aces_1", "Aces_2",
                 "ServesTotal_1", "ServesTotal_2", "Aces_L5_1", "Aces_A_1"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def inspect(source: Path, expected_sha256: str) -> dict:
    if not source.is_file() or source.suffix.lower() != ".csv":
        raise ValueError("Expected local CSV")
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("Source exceeds limit")
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError("Expected exact lower-case SHA-256")
    if digest(source) != expected_sha256:
        raise ValueError("Source SHA-256 mismatch")
    counts = Counter()
    csv.field_size_limit(1024**2)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        if not headers or not SOURCE_FIELDS.issubset(set(headers)):
            raise ValueError("Unknown source schema, refusing guesses")
        for row in reader:
            counts['source_rows'] += 1
            if counts['source_rows'] > MAX_ROWS:
                raise ValueError("Source row limit exceeded")
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed source CSV")
            year = str(row['GameD'])[:4]
            if not (year.isdigit() and 2016 <= int(year) <= 2020):
                counts['outside_2016_2020'] += 1
                continue
            counts['rows_2016_2020'] += 1
            for side in (1, 2):
                historical_round = row[f'RID_{side}']
                current_round = row['RID_CUR']
                if historical_round.strip():
                    counts[f'historical_round_present_{side}'] += 1
                    try:
                        different = float(historical_round) != float(current_round)
                    except (ValueError, TypeError):
                        different = True
                    if different:
                        counts[f'historical_round_differs_{side}'] += 1
                if side == 1 and row[f'GRes_{side}'].strip() and row['GRes_CUR_1'].strip():
                    counts[f'historical_result_present_{side}'] += 1
                    try:
                        different = float(row[f'GRes_{side}']) != float(row['GRes_CUR_1'])
                    except (ValueError, TypeError):
                        different = True
                    if different:
                        counts[f'historical_result_differs_{side}'] += 1
    if digest(source) != expected_sha256:
        raise ValueError("Source changed during audit")
    # No inferred mapping from _1/_2 lookbacks to the _CUR match is permitted.
    return {
        'schema': 1,
        'source_sha256': expected_sha256,
        'state': 'QUARANTINED_LOOKBACK_NOT_MATCH_STATS',
        'production_mutated': False,
        'api_requests': 0,
        'current_match_stat_values_eligible': 0,
        'canonical_matches_confirmed': 0,
        'counts': dict(sorted(counts.items())),
        'rationale': ('_CUR columns describe the listed match; _1/_2 are distinct history '
                      'blocks with independently varying RID/GRes. No match identity for '
                      'their underlying observations is provided.'),
        'required_next_step': ('Find original match-level source or independently reconstruct '
                               'the historical observation identity and point-in-time provenance.'),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--expected-sha256', required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    report = inspect(args.source, args.expected_sha256)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'counts'}, sort_keys=True))

if __name__ == '__main__':
    main()
