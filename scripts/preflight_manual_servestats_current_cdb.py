#!/usr/bin/env python3
"""Private, exact-event read-only bridge: saved serve stats vs current canonical CDB.

Never modifies history, uploads canonical assets, contacts tennis providers or
performs model training. Reports research-only delta; import eligibility requires
separately attested source rights and a governed canonical writer.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def record_time(value):
    value = pd.Timestamp(value)
    if pd.isna(value):
        return None
    if value.tzinfo is None:
        return None
    return value.tz_convert("UTC").isoformat()


def strict_dict(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        result = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if isinstance(result, dict):
            return result
    raise ValueError("malformed canonical JSON")


def event_id(ctx):
    ids = []
    for key in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id"):
        if ctx.get(key) not in (None, ""):
            ids.append(str(ctx[key]))
    event = ctx.get("event")
    if isinstance(event, dict) and event.get("id") not in (None, ""):
        ids.append(str(event["id"]))
    identity = ctx.get("_tbt_event_identity")
    if isinstance(identity, dict) and identity.get("event_id") not in (None, ""):
        ids.append(str(identity["event_id"]))
    marker = ctx.get("_tbt_statistics")
    if isinstance(marker, dict) and marker.get("event_id") not in (None, ""):
        ids.append(str(marker["event_id"]))
    if not ids or len(set(ids)) != 1:
        return None
    return ids[0]


def side_proof(ctx, canonical, expected_event):
    """Use exact original event identity; never infer orientation from names."""
    identity = ctx.get("_tbt_event_identity")
    if not isinstance(identity, dict) or str(identity.get("event_id")) != expected_event:
        return None
    def source_id(value):
        if isinstance(value, dict):
            value = value.get("id")
        return str(value).strip() if value not in (None, "") else ""
    sides = [(source_id((ctx.get(k) or {}).get("id")) if isinstance(ctx.get(k), dict)
              else "") for k in ("homeTeam", "awayTeam")]
    if not all(sides):
        sides = [source_id(identity.get("home")), source_id(identity.get("away"))]
    if not sides[0] or not sides[1] or sides[0] == sides[1]:
        return None
    p1, p2 = str(canonical["player1_id"]), str(canonical["player2_id"])
    if (p1, p2) == tuple(sides):
        first = "home"
    elif (p1, p2) == tuple(reversed(sides)):
        first = "away"
    else:
        return None
    return {
        "match_id": str(canonical["match_id"]),
        "event_id": expected_event,
        "player1_id": p1, "player2_id": p2,
        "evidence_kind": "provider_player_ids_both",
        "provider_id_namespace": "provider_event",
        "home_provider_player_id": sides[0],
        "away_provider_player_id": sides[1],
        "p1_provider_side": first,
        "p1_provider_player_id": sides[0] if first == "home" else sides[1],
        "p2_provider_player_id": sides[1] if first == "home" else sides[0],
        "orientation_attested_by": "independent_provider_event_participants",
    }


def stage(source, years, output):
    from audit_manual_servestats_cdb import audit, read_jsonl, stamp
    source = Path(source)
    input_rows = list(read_jsonl(source))
    ids = set()
    source_by_id = {}
    for row in input_rows:
        mid = row.get("match_id")
        if not isinstance(mid, str) or mid in ids:
            raise ValueError("invalid or duplicate raw match_id")
        ids.add(mid)
        source_by_id[mid] = row

    counters = Counter(source_rows=len(input_rows))
    canonical_rows = []
    witnesses = []
    matched = set()
    needed = ["match_id", "tour", "scheduled_at", "player1_id",
              "player2_id", "stats_json", "provider_context_json"]
    for year in years:
        frame = pd.read_parquet(year, columns=needed)
        counters["canonical_rows_examined"] += len(frame)
        for row in frame.itertuples(index=False, name=None):
            r = dict(zip(needed, row))
            mid = str(r["match_id"])
            if mid not in ids:
                continue
            if mid in matched:
                raise ValueError("one raw match_id appears in multiple canonical partitions")
            matched.add(mid)
            counters["canonical_match_id_overlap"] += 1
            try:
                ctx = strict_dict(r["provider_context_json"])
                r["event_id"] = event_id(ctx)
                r["scheduled_at"] = record_time(r["scheduled_at"])
                if not r["event_id"] or not r["scheduled_at"]:
                    counters["missing_trusted_event_or_utc"] += 1
                    continue
                if str(source_by_id[mid]["event_id"]) != r["event_id"]:
                    counters["different_provider_event_id"] += 1
                    continue
                if str(source_by_id[mid]["tour"]).lower() != str(r["tour"]).lower():
                    counters["different_tour"] += 1
                    continue
                if stamp(r["scheduled_at"]) != stamp(source_by_id[mid]["scheduled_at"]):
                    counters["different_event_start_time"] += 1
                    continue
                r["stats_json"] = strict_dict(r["stats_json"])
                counters["exact_provider_event_and_clock"] += 1
                canonical_rows.append(r)
                witness = side_proof(ctx, r, r["event_id"])
                if witness:
                    counters["strict_two_player_orientation_evidence"] += 1
                    witnesses.append(witness)
                else:
                    counters["unproven_original_player_orientation"] += 1
            except (ValueError, TypeError, KeyError):
                counters["malformed_or_unverifiable_cdb_context"] += 1
                continue

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    canon = output / "canonical-candidate-rows.jsonl"
    wit = output / "independent-orientation-witness.jsonl"
    canon.write_text("".join(json.dumps(r, default=str, ensure_ascii=False) + "\n"
                             for r in canonical_rows), encoding="utf-8")
    wit.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                           for r in witnesses), encoding="utf-8")
    detailed = audit(source, canon, wit, expected_source_sha256=sha256(source),
                     expected_canonical_sha256=sha256(canon))
    counters.update(detailed["counts"])
    # Counter.update ADDS shared keys. Source records were counted once above;
    # prevent audit output from falsely reporting the same 575 twice.
    counters["source_rows"] = len(input_rows)
    safe = {
        "schema": 1, "status": "CDB_CURRENT_TWO_YEAR_SOURCE_NULL_PREFLIGHT",
        "scope": "2025-2026",
        "source_sha256": sha256(source),
        "canonical_years_sha256": {Path(p).name: sha256(p) for p in years},
        "counts": dict(sorted(counters.items())),
        "rights_evidence_verified": False,
        "canonical_writer_invoked": False, "write_authorized": False,
        "production_mutated": False, "model_trained": False,
        "new_crons": 0, "provider_api_requests": 0,
        "next_gate": "Original provider participant crosswalk, reuse rights and current NULL-only writer CAS",
    }
    (output / "report.json").write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "research-only-candidates.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n"
                for r in detailed["research_only_candidates"]), encoding="utf-8")
    return safe


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--source", required=True)
    a.add_argument("--year", action="append", required=True)
    a.add_argument("--output", required=True)
    args = a.parse_args()
    report = stage(args.source, args.year, args.output)
    print(json.dumps({k: v for k, v in report.items() if k not in ("source_sha256", "canonical_years_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
