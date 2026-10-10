"""Attach verified US Open 2024 serve observations to existing canonical match payloads.

Research-only metadata. No changes to canonical match fields, ranks or stats.
Stage mode is dry-run; write mode only modifies local history partitions.
Publication requires an external immutable backup and independent readback.
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

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_odds import norm_text

SOURCE_BLOB = "9d0a7a8c013a68d18e437f8c75f8fb7c036f1224"
SOURCE_NAME = "jasnwag/tennis_serve_dataset"
MARKER_KEY = "_tbt_usopen_2024_serve_research"
POLICY = "research_post_match_only; same-match fields forbidden as pre-match features; eligible only for strictly lagged chronological player-state experiments"
COUNT_FIELDS = {"serve_rows", "speed_observations", "ace_count", "serve_number_1_rows",
                "serve_number_2_rows", "service_games_observed", "sets_observed"}
SPEED_FIELDS = {"speed_kmh_mean", "speed_kmh_median", "speed_kmh_max",
                "first_serve_speed_kmh_mean", "second_serve_speed_kmh_mean"}
OTHER_FIELDS = {"height_cm", "ace_rate_per_serve_row", "quality_label_mean",
                "rally_count_mean", "rally_count_median", "serve_duration_sec_mean"}
DICT_FIELDS = {"serve_width_counts", "serve_depth_counts", "opponent_return_depth_counts"}
ALLOWED = COUNT_FIELDS | SPEED_FIELDS | OTHER_FIELDS | DICT_FIELDS


def _finite(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Unexpected numeric serve value")
    x = float(value)
    if not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError("Out-of-range serve observation")
    return x


def _serve(raw):
    if not isinstance(raw, dict) or set(raw) != ALLOWED:
        raise ValueError("Unexpected serve metadata schema")
    stats = {}
    for key, val in raw.items():
        if val is None:
            stats[key] = None
        elif key in COUNT_FIELDS:
            x = _finite(val, 0, 1000)
            if not x.is_integer():
                raise ValueError("Fractional serve count")
            stats[key] = int(x)
        elif key in SPEED_FIELDS:
            stats[key] = _finite(val, 60, 290)
        elif key == "height_cm":
            stats[key] = _finite(val, 120, 240)
        elif key == "ace_rate_per_serve_row":
            stats[key] = _finite(val, 0, 1)
        elif key == "quality_label_mean":
            stats[key] = _finite(val, 0, 10)
        elif key == "serve_duration_sec_mean":
            stats[key] = _finite(val, 0, 40)
        elif key in {"rally_count_mean", "rally_count_median"}:
            stats[key] = _finite(val, 0, 200)
        elif key in DICT_FIELDS:
            if not isinstance(val, dict) or any(not isinstance(k, str) or not k or len(k) > 20 for k in val):
                raise ValueError("Malformed serve category counts")
            stats[key] = {}
            for k, v in val.items():
                n = _finite(v, 0, 1000)
                if not n.is_integer():
                    raise ValueError("Fractional serve category counts")
                stats[key][k] = int(n)
        else:
            raise ValueError("Unexpected serve field")
    if not isinstance(stats["serve_rows"], int) or stats["serve_rows"] <= 0:
        raise ValueError("Missing serve observations")
    if not isinstance(stats["speed_observations"], int) or not 0 < stats["speed_observations"] <= stats["serve_rows"]:
        raise ValueError("Bad speed denominator")
    if any(stats[k] is None for k in ("speed_kmh_mean", "speed_kmh_median", "speed_kmh_max")):
        raise ValueError("Missing required serve speed")
    if stats["speed_kmh_max"] < stats["speed_kmh_mean"]:
        raise ValueError("Serve speed summary inconsistent")
    return stats


def _signature(match):
    return {
        "match_id": str(match.match_id),
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
        "player1_id": str(match.player1_id),
        "player2_id": str(match.player2_id),
        "player1_name_norm": norm_text(match.player1_name),
        "player2_name_norm": norm_text(match.player2_name),
    }


def _validate_raw(row):
    if not isinstance(row, dict) or row.get("schema") != 2:
        raise ValueError("Invalid serve-source record schema")
    if (row.get("source") != SOURCE_NAME or row.get("license") != "CC BY 4.0"
            or row.get("source_event") != "US Open 2024" or row.get("feature_policy") != POLICY
            or "unique canonical match" not in str(row.get("evidence") or "")):
        raise ValueError("Unverified serve source attribution or evidence")
    if row.get("tour") not in {"atp", "wta"} or not str(row.get("scheduled_date_utc") or "").startswith("2024-"):
        raise ValueError("Wrong tour or year")
    if "us open" not in norm_text(row.get("tournament")):
        raise ValueError("Wrong source event")
    if not row.get("source_match_id") or not row.get("match_id"):
        raise ValueError("Missing stable source identity")
    side1, side2 = _serve(row.get("player1_serve")), _serve(row.get("player2_serve"))
    return {
        "schema": 1, "source": SOURCE_NAME,
        "source_ref_blob_sha": SOURCE_BLOB, "source_event": "US Open 2024",
        "source_match_id": str(row["source_match_id"]), "license": "CC BY 4.0",
        "feature_policy": POLICY, "player1_serve": side1, "player2_serve": side2,
    }


def _stage_row(row, match):
    marker = _validate_raw(row)
    actual = _signature(match)
    expected = {
        "match_id": str(row["match_id"]), "tour": str(row["tour"]).lower(),
        "scheduled_date_utc": str(row["scheduled_date_utc"]),
        "player1_id": str(row.get("player1_id")), "player2_id": str(row.get("player2_id")),
        "player1_name_norm": norm_text(row.get("player1_name")),
        "player2_name_norm": norm_text(row.get("player2_name")),
    }
    if actual != expected:
        raise ValueError("Canonical match identity does not match source")
    if "us open" not in norm_text(match.tournament):
        raise ValueError("Canonical event mismatched")
    return {"schema": 1, "match_id": actual["match_id"], "canonical": actual,
            "marker": marker, "import_ready": True}


def read_source(path: Path):
    blob = path.read_bytes()
    real = hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest()
    if real != SOURCE_BLOB:
        raise ValueError("Pinned source blob SHA does not match")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def stage(matches, raw_rows):
    by_id = {str(match.match_id): match for match in matches}
    if len(by_id) != len(matches):
        raise ValueError("Nonunique canonical match IDs")
    seen_source, seen_canonical, accepted = set(), set(), []
    counts = Counter()
    for row in raw_rows:
        counts["source_rows"] += 1
        if not isinstance(row, dict):
            raise ValueError("Malformed source record")
        mid, source_id = str(row.get("match_id") or ""), str(row.get("source_match_id") or "")
        if not mid or mid in seen_canonical or source_id in seen_source:
            raise ValueError("Duplicate source or canonical match")
        seen_canonical.add(mid)
        seen_source.add(source_id)
        match = by_id.get(mid)
        if match is None:
            counts["identity_missing"] += 1
            continue
        rec = _stage_row(row, match)
        prior = (match.provider_payload or {}).get(MARKER_KEY)
        if prior is not None:
            if prior != rec["marker"]:
                raise ValueError("Conflicting preexisting serve marker")
            counts["already_present"] += 1
            continue
        accepted.append(rec)
        counts["staged"] += 1
    if not counts["source_rows"]:
        raise ValueError("Empty serve source")
    return accepted, dict(counts)


def write_local(matches, stage_rows):
    by_id = {str(match.match_id): match for match in matches}
    if len(by_id) != len(matches):
        raise ValueError("Nonunique canonical match IDs")
    seen = set()
    changed = set()
    for row in stage_rows:
        if row.get("schema") != 1 or row.get("import_ready") is not True:
            raise ValueError("Invalid staged trust marker")
        mid = str(row.get("match_id") or "")
        if not mid or mid in seen:
            raise ValueError("Duplicate staged match ID")
        seen.add(mid)
        match = by_id.get(mid)
        if match is None or row.get("canonical") != _signature(match):
            raise ValueError("Canonical identity changed since dry-run")
        if (match.provider_payload or {}).get(MARKER_KEY) is not None:
            raise ValueError("Existing serve metadata marker; refuse overwrite")
        marker = row.get("marker")
        if not isinstance(marker, dict) or marker.get("source_ref_blob_sha") != SOURCE_BLOB:
            raise ValueError("Invalid staged source provenance")
        payload = dict(match.provider_payload or {})
        payload[MARKER_KEY] = marker
        match.provider_payload = payload
        changed.add(int(match.scheduled_at.year))
    return sorted(changed)


def write_exact_serve_markers(history_dir: Path, stage_rows: list[dict]) -> list[int]:
    """Patch only staged Parquet provider_context_json cells.

    A full MatchRecord -> Parquet rewrite is unsafe for this sidecar: legacy
    unrelated rows can be re-normalized by the general snapshot serializer.
    The prepublication full readback below still rejects ANY collateral change.
    """
    import pandas as pd

    from tbt.data.history_snapshot import (
        load_manifest, load_snapshot, partition_path, update_year_manifest,
    )
    from verify_usopen_serve_readback import verify

    if not stage_rows:
        return []
    if len({str(r.get("match_id")) for r in stage_rows}) != len(stage_rows):
        raise ValueError("Duplicate staged match identity")
    years = {int(r["canonical"]["scheduled_date_utc"][:4]) for r in stage_rows}
    if years != {2024}:
        raise ValueError("US Open sidecar may change only UTC year 2024")
    path = partition_path(history_dir, 2024)
    if not path.is_file():
        raise FileNotFoundError("Missing backed-up 2024 history partition")
    frame = pd.read_parquet(path, engine="pyarrow")
    required = {"match_id", "provider_context_json", "scheduled_at"}
    if not required.issubset(frame.columns):
        raise ValueError("Missing canonical Parquet columns")
    ids = frame["match_id"].astype(str)
    if ids.duplicated().any():
        raise ValueError("Duplicate 2024 canonical match IDs")
    by_id = dict(zip(ids, frame.index))
    before = load_snapshot(path)
    if len(before) != len(frame):
        raise ValueError("Canonical partition count mismatch")
    matches = {str(match.match_id): match for match in before}
    if len(matches) != len(before):
        raise ValueError("Canonical partition identity collision")
    original_other_columns = frame.drop(columns=["provider_context_json"]).copy(deep=True)
    unchanged_payload = frame["provider_context_json"].copy(deep=True)
    touched: set[int] = set()
    for item in stage_rows:
        mid = str(item["match_id"])
        if mid not in by_id or mid not in matches:
            raise ValueError(f"Staged canonical identity missing: {mid}")
        if item.get("schema") != 1 or item.get("import_ready") is not True:
            raise ValueError("Invalid staged trust marker")
        if _signature(matches[mid]) != item.get("canonical"):
            raise ValueError(f"Canonical identity changed since staging: {mid}")
        marker = item.get("marker")
        if not isinstance(marker, dict) or marker.get("source_ref_blob_sha") != SOURCE_BLOB:
            raise ValueError("Unverified staged source provenance")
        row_index = by_id[mid]
        # Use the original on-disk JSON, not the potentially normalized
        # MatchRecord.provider_payload. Never erase any preexisting context.
        raw = frame.at[row_index, "provider_context_json"]
        if not isinstance(raw, str):
            raise ValueError(f"Missing original provider context: {mid}")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid provider context: {mid}")
        if payload.get(MARKER_KEY) is not None:
            raise ValueError(f"Existing serve marker; refuse overwrite: {mid}")
        payload[MARKER_KEY] = marker
        frame.at[row_index, "provider_context_json"] = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        touched.add(row_index)
    pd.testing.assert_frame_equal(
        frame.drop(columns=["provider_context_json"]),
        original_other_columns,
        check_dtype=True,
    )
    if not frame.loc[~frame.index.isin(touched), "provider_context_json"].equals(
        unchanged_payload.loc[~frame.index.isin(touched)]
    ):
        raise ValueError("Unstaged provider context changed before write")
    temporary = path.with_name(path.name + ".usopen-exact.tmp")
    try:
        frame.to_parquet(temporary, engine="pyarrow", compression="zstd", index=False)
        if temporary.stat().st_size <= 0:
            raise ValueError("Empty staged history partition")
        comparison = verify(before, load_snapshot(temporary), stage_rows)
        if comparison["enriched_matches"] != len(stage_rows):
            raise ValueError("Incomplete local US Open marker readback")
        meta = load_manifest(history_dir).get("years", {}).get("2024")
        if not isinstance(meta, dict) or int(meta.get("rows", -1)) != len(frame):
            raise ValueError("Canonical 2024 manifest row count mismatch")
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        size = temporary.stat().st_size
        temporary.replace(path)
        update_year_manifest(history_dir, 2024, {
            "sha256": digest, "bytes": size, "rows": len(frame),
        }, extra={"coverage_status": "verified_usopen_2024_serve_research"})
    finally:
        if temporary.exists():
            temporary.unlink()
    return [2024]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("stage", "write"), required=True)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--stage-file", type=Path)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Nonempty canonical identity quarantine")
    if args.mode == "stage":
        if args.source is None:
            ap.error("--source required for staging")
        staged, counts = stage(matches, read_source(args.source))
        with (out / "verified_stage.jsonl").open("w", encoding="utf-8") as fh:
            for rec in staged:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        report = {"schema": 1, "mode": "stage", "canonical_rows": len(matches),
                  "counts": counts, "source_blob": SOURCE_BLOB, "changed_years": [2024] if staged else [],
                  "api_requests": 0, "canonical_mutated": False}
    else:
        if args.stage_file is None:
            ap.error("--stage-file required for local write")
        staged = [json.loads(s) for s in args.stage_file.read_text(encoding="utf-8").splitlines() if s.strip()]
        years = write_local(matches, staged)
        if years:
            patched_years = write_exact_serve_markers(Path(args.history_dir), staged)
            if years != patched_years:
                raise ValueError("Parquet patch affected unexpected canonical years")
        report = {"schema": 1, "mode": "write", "canonical_rows": len(matches),
                  "counts": {"updated": len(staged)}, "source_blob": SOURCE_BLOB,
                  "changed_years": years, "api_requests": 0, "canonical_mutated": False}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
