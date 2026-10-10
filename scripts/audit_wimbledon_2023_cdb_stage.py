"""Read-only, source-pinned 2023 Wimbledon point-to-CDB completeness audit.

Never publishes CDB data, never treats a partial point tape as a whole match,
and does not confer model-training or write permission on any candidate.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import timezone
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from link_wimbledon_2023_advanced import (
    REQUIRED, _canonical_index, _canonical_winner_side, _safe_scalar,
    _source_to_canonical_orientation, _validate_group, _winner_from_sets, _int,
)
from tbt.data.history_snapshot import load_manifest, load_snapshot

SOURCE_SHA = "19507e156e6ff307027d39e44000ac446a564f87b3c8d59a5225dc6d1674c512"
SIDECAR_SHA = "8c9b00eb96582cb5bfe3449b0bdb2dffbfb11d3fc387e54e142d645e6d43e316"
LICENSE_SHA = "4b1a12b70abaaa9536dc0e371c177549863d131db3bc273e6768354f3b1e1df9"
DOI = "10.6084/m9.figshare.25511917"
FIELDS = (
    ("p1_aces", "p1_ace", "aces", 1),
    ("p2_aces", "p2_ace", "aces", 2),
    ("p1_double_faults", "p1_double_fault", "double_faults", 1),
    ("p2_double_faults", "p2_double_fault", "double_faults", 2),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, expected: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise ValueError(f"Unverified source bytes: {path.name}")


def clean_binary(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) and number in (0.0, 1.0) else None


def tape_completeness(group: pd.DataFrame, best_of, winner_side: int | None) -> list[str]:
    """Conservative terminal match proof; no source-specific inferred padding."""
    problems = list(_validate_group(group))
    rows = group.sort_values("point_no", kind="stable")
    numbers = pd.to_numeric(rows["point_no"], errors="coerce").tolist()
    n = len(rows)
    if numbers != list(range(1, n + 1)):
        problems.append("nonexhaustive_point_sequence")
    if n == 0:
        problems.append("empty_tape")
        return sorted(set(problems))
    wins1 = pd.to_numeric(rows["set_victor"], errors="coerce").eq(1)
    wins2 = pd.to_numeric(rows["set_victor"], errors="coerce").eq(2)
    n1, n2 = int(wins1.sum()), int(wins2.sum())
    if best_of is None or str(best_of) not in ("3", "5"):
        problems.append("unknown_match_format")
    else:
        required = int(best_of) // 2 + 1
        if sorted((n1, n2)) != [min(n1, n2), required] or min(n1, n2) >= required:
            problems.append("missing_or_excess_terminal_set")
        if winner_side not in (1, 2) or (n1 if winner_side == 1 else n2) != required:
            problems.append("set_victor_not_canonical_winner")
        if _int(rows["set_victor"].iloc[-1]) != winner_side:
            problems.append("last_point_not_match_terminal_set")
    # A winning set must end on a won game; an implausibly short point tape
    # cannot masquerade as a fully observed tennis match.
    game_winners = pd.to_numeric(rows["game_victor"], errors="coerce")
    games1 = int(game_winners.eq(1).sum())
    games2 = int(game_winners.eq(2).sum())
    if _int(rows["set_victor"].iloc[-1]) in (1, 2):
        if _int(rows["game_victor"].iloc[-1]) != winner_side:
            problems.append("terminal_set_without_game_victor")
    if n1 > 0 and games1 < 6 * n1:
        problems.append("implausibly_few_games_for_player1_sets")
    if n2 > 0 and games2 < 6 * n2:
        problems.append("implausibly_few_games_for_player2_sets")
    for _, raw_field, _, _ in FIELDS:
        if any(clean_binary(x) is None for x in rows[raw_field]):
            problems.append(f"missing_or_invalid_point_flags:{raw_field}")
    return sorted(set(problems))


def classify(value: int | None, existing, tape_issues: list[str]) -> tuple[str, list[str]]:
    if tape_issues or value is None:
        return "UNRESOLVED", tape_issues or ["unverified_whole_match_count"]
    if existing is None:
        return "READY_MISSING", ["verified_complete_tape_and_absent_canonical_cell"]
    if isinstance(existing, bool):
        return "UNRESOLVED", ["canonical_count_invalid_bool"]
    try:
        numeric = float(existing)
    except (ValueError, TypeError):
        return "UNRESOLVED", ["canonical_count_invalid_type"]
    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        return "UNRESOLVED", ["canonical_count_invalid_value"]
    return ("ALREADY_PRESENT", ["same_exact_count"]) if int(numeric) == value else (
        "CONFLICT", ["source_and_canonical_counts_disagree"]
    )


def _read_sidecar(path: Path) -> dict[str, dict]:
    rows = {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            source_mid = str(record.get("source_match_id") or "")
            if not source_mid or source_mid in rows:
                raise ValueError("Missing or duplicate research source match identifier")
            rows[source_mid] = record
    return rows


def _current_release(year_file: Path, manifest: Path, release_metadata: Path) -> str:
    parsed = load_manifest(manifest.parent)
    metadata = (parsed.get("years") or {}).get("2023") or {}
    digest = sha256(year_file)
    if metadata.get("sha256") != digest or metadata.get("asset") != "history-2023.parquet":
        raise ValueError("2023 CDB partition does not match authoritative manifest")
    release = json.loads(release_metadata.read_text())
    assets = {a["name"]: a for a in release.get("assets", [])}
    for path in (year_file, manifest):
        declared = assets.get(path.name, {}).get("digest")
        if declared != "sha256:" + sha256(path):
            raise ValueError("Latest release asset metadata disagrees with downloaded bytes: " + path.name)
    return digest


def _raw_and_sidecar_equal(group: pd.DataFrame, stored: dict) -> bool:
    raw_rows = [
        {str(k): _safe_scalar(v) for k, v in row.items()}
        for row in group.sort_values("point_no", kind="stable").to_dict(orient="records")
    ]
    relevant = ("point_no", "p1_ace", "p2_ace", "p1_double_fault", "p2_double_fault",
                "set_victor", "point_victor", "server", "p1_points_won", "p2_points_won")
    derived = stored.get("points")
    if not isinstance(derived, list) or len(derived) != len(raw_rows):
        return False
    return all(
        all(str(left.get(k)) == str(right.get(k)) for k in relevant)
        for left, right in zip(raw_rows, derived)
    )


def _observation(match, source_mid, group, sidecar, field, raw_field, agg, side,
                 complete_issues, cdb_sha):
    reversed_sides = sidecar["source_orientation"] == "reversed"
    source_side = 3 - side if reversed_sides else side
    raw = f"p{source_side}_{raw_field[3:]}"
    flags = [clean_binary(x) for x in group[raw]]
    raw_count = sum(v for v in flags if v is not None)
    advanced = sidecar.get(f"player{side}_advanced") or {}
    issues = list(complete_issues)
    if advanced.get(agg) != raw_count:
        issues.append(f"sidecar_aggregate_disagrees:{field}")
    if not isinstance(match.stats, dict):
        issues.append("canonical_stats_not_object")
        stats = {}
    else:
        stats = match.stats
    value = raw_count if not issues else None
    other = stats.get(field)
    state, reasons = classify(value, other, sorted(set(issues)))
    source_p1 = str(group["player1"].iloc[0])
    source_p2 = str(group["player2"].iloc[0])
    return {
        "contract_version": "1.0.0",
        "source_id": "figshare_wimbledon_2023_momentum",
        "source_version": {"content_sha256": SOURCE_SHA, "version_label": DOI},
        "source_record_id": f"{source_mid}:whole_match:{field}",
        "source_identity": {
            "provider_match_id": str(source_mid), "original_player1": source_p1,
            "original_player2": source_p2, "original_tournament": "Wimbledon",
            "original_match_date": None, "tour": str(match.tour or "unknown").upper(),
            "source_player_ids": [None, None],
        },
        "canonical_match_id": str(match.match_id),
        "player_orientation": {
            "relation": "reversed" if reversed_sides else "same",
            "source_subject": source_p1 if source_side == 1 else source_p2,
            "canonical_subject": str(match.player1_name if side == 1 else match.player2_name),
            "swapped": reversed_sides,
        },
        "match_evidence": {
            "identity_policy": "year+Wimbledon+exact_normalized_pair+winner+unique_candidate",
            "evidence_references": [f"figshare:{DOI}", f"cdb-2023:{cdb_sha}",
                                    f"sidecar-sha256:{SIDECAR_SHA}"],
            "ambiguity_candidates": 1,
        },
        "field": field, "value": value, "unit": "count", "scope": "whole_match",
        "methodology": ("complete_point_event_binary_flag_count" if not issues
                        else "partial_or_unverified_point_count_not_whole_match"),
        "event_time": None, "available_at": None,
        "transformation": {
            "version": "wimbledon-point-count-audit-v1",
            "operations": ["point_flag_count", "source_to_canonical_side_swap" if reversed_sides else "same_orientation"],
            "raw_value": raw_count, "raw_unit": "point_events_count",
        },
        "provenance": {
            "upstream_family": "figshare_wimbledon_2023_momentum",
            "raw_locator": f"figshare:{DOI} / {source_mid}",
            "raw_content_sha256": SOURCE_SHA,
            "license_basis": "CC BY 4.0 (source metadata and sha256-pinned license note)",
            "independent_of": [],
            "source_url": "https://doi.org/" + DOI,
        },
        "validation": {
            "state": state, "reasons": reasons,
            "validated_against_cdb_sha256": cdb_sha,
            "expected_original_value": other,
            "proof_refs": [f"release:tbt-data-v1:history-2023.parquet:{cdb_sha}"],
        },
        "import_eligibility": "candidate_after_package_review" if state == "READY_MISSING" else "blocked",
        "model_eligibility": (
            "postmatch_only_for_future_matches" if state == "READY_MISSING" else "research_only"
        ),
    }


def run(workbook: Path, sidecar: Path, license_note: Path, year_file: Path,
        manifest: Path, release_metadata: Path, schema_file: Path, out_dir: Path) -> dict:
    import jsonschema
    verify_file(workbook, SOURCE_SHA)
    verify_file(sidecar, SIDECAR_SHA)
    verify_file(license_note, LICENSE_SHA)
    note = license_note.read_text(encoding="utf-8")
    if "CC BY 4.0" not in note:
        raise ValueError("Specific source license basis is not verified")
    cdb_sha = _current_release(year_file, manifest, release_metadata)
    schema = json.loads(schema_file.read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    matches = load_snapshot(year_file)
    match_by_id = {str(m.match_id): m for m in matches}
    if len(match_by_id) != len(matches):
        raise ValueError("Duplicate current canonical IDs in 2023 partition")
    candidate_index = _canonical_index(matches)
    archived = _read_sidecar(sidecar)
    source = pd.read_excel(workbook, sheet_name=0)
    if not REQUIRED.issubset(set(map(str, source.columns))):
        raise ValueError("Raw source required point columns missing")
    observations, review = [], []
    counts = Counter()
    for source_mid, group in sorted(source.groupby("match_id", sort=False),
                                    key=lambda pair: str(pair[0])):
        source_mid = str(source_mid)
        counts["raw_matches"] += 1
        counts["raw_points"] += len(group)
        stored = archived.get(source_mid)
        issues = []
        if not stored:
            issues.append("missing_pinned_research_sidecar_link")
            review.append({"source_match_id": source_mid, "reasons": issues})
            counts["unresolved_matches"] += 1
            continue
        match = match_by_id.get(str(stored.get("match_id") or ""))
        if match is None or match.scheduled_at.astimezone(timezone.utc).year != 2023:
            issues.append("canonical_match_missing_or_wrong_year")
            review.append({"source_match_id": source_mid, "reasons": issues})
            counts["unresolved_matches"] += 1
            continue
        pair = tuple(sorted((
            str(x).strip().lower() for x in (group["player1"].iloc[0], group["player2"].iloc[0])
        )))
        # The linked sidecar alone is not independent identity evidence.
        from tbt.data.offline_odds import norm_text
        index_key = tuple(sorted((norm_text(group["player1"].iloc[0]),
                                  norm_text(group["player2"].iloc[0]))))
        unique = candidate_index.get(index_key, [])
        if len(unique) != 1 or str(unique[0].match_id) != str(match.match_id):
            issues.append("nonunique_current_wimbledon_pair")
        orientation = _source_to_canonical_orientation(group, match)
        if orientation is None or stored.get("source_orientation") != orientation:
            issues.append("source_canonical_side_swap_unverified")
        source_winner = _winner_from_sets(group)
        canonical_winner = _canonical_winner_side(match)
        if orientation and source_winner in (1, 2) and canonical_winner in (1, 2):
            expected = source_winner if orientation == "direct" else 3 - source_winner
            if expected != canonical_winner:
                issues.append("canonical_winner_disagreement")
        else:
            issues.append("winner_not_proven")
        if not _raw_and_sidecar_equal(group, stored):
            issues.append("archived_point_tape_differs_from_pinned_workbook")
        if str(stored.get("tour") or "").lower() != str(match.tour or "").lower():
            issues.append("tour_changed")
        if stored.get("player1_id") != str(match.player1_id) or stored.get("player2_id") != str(match.player2_id):
            issues.append("canonical_player_id_changed")
        source_winner_canonical = source_winner if orientation == "direct" else (
            3 - source_winner if orientation == "reversed" and source_winner in (1, 2) else None
        )
        winner_for_raw = source_winner if source_winner in (1, 2) else None
        issues.extend(tape_completeness(group, match.best_of, winner_for_raw))
        if issues:
            counts["unresolved_matches"] += 1
            review.append({"source_match_id": source_mid, "canonical_match_id": str(match.match_id),
                           "reasons": sorted(set(issues)), "point_rows": len(group)})
        else:
            counts["tape_complete_matches"] += 1
        for field, raw_field, aggregate, side in FIELDS:
            item = _observation(match, source_mid, group, stored, field, raw_field,
                                aggregate, side, sorted(set(issues)), cdb_sha)
            validator.validate(item)
            observations.append(item)
            counts[item["validation"]["state"]] += 1
        counts["linked_matches_compared"] += 1
    if set(archived) != {str(x) for x in source["match_id"].dropna().unique()}:
        raise ValueError("Pinned research sidecar/raw source match inventory differs")
    if counts["raw_matches"] != 5 or counts["raw_points"] != 774 or counts["linked_matches_compared"] != 5:
        raise ValueError("Pilot cardinality diverges from source-linked audit")
    if len(observations) != 20 or len({(o["canonical_match_id"], o["field"]) for o in observations}) != 20:
        raise ValueError("Missing, duplicate or aliased canonical match fields")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "observations.jsonl").open("w", encoding="utf-8") as stream:
        for obs in observations:
            stream.write(json.dumps(obs, ensure_ascii=False, allow_nan=False) + "\n")
    with (out_dir / "quarantine.jsonl").open("w", encoding="utf-8") as stream:
        for entry in review:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    report = {
        "schema": 1, "status": "read_only_classified",
        "source_sha256": SOURCE_SHA, "sidecar_sha256": SIDECAR_SHA,
        "license_note_sha256": LICENSE_SHA, "cdb_year": 2023,
        "cdb_partition_sha256": cdb_sha, "canonical_year_rows": len(matches),
        "counts": dict(counts), "observation_rows": len(observations),
        "quarantined_matches": len(review), "api_requests": 0,
        "production_mutated": False, "write_authorized": False,
        "model_training_performed": False, "model_promoted": False,
        "eligibility_note": "READY_MISSING never authorizes publication; isolated replay, writer lock, full backup and independent persisted readback required",
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ("workbook", "sidecar", "license_note", "year_file",
                 "manifest", "release_metadata", "schema_file", "out_dir"):
        parser.add_argument("--" + name.replace("_", "-"), required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), indent=2))


if __name__ == "__main__":
    main()
