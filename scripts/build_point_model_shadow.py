#!/usr/bin/env python3
"""Build a local, atomic admin shadow snapshot from canonical history and fixtures."""
import argparse
from dataclasses import fields
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.models.point_model import PointHistory, timestamp
from tbt.models.point_anchor import CANDIDATE, MODEL_SHA
from tbt.schemas import MatchRecord
from tbt.services.data_quality import audit_history


def fixtures_from_json(payload, as_of):
    fixtures = []
    seen = set()
    allowed = {f.name for f in fields(MatchRecord)} - {"stats", "winner_id", "status", "best_of", "provider_payload"}
    for row in payload["fixtures"]:
        starts = timestamp(row.get("scheduled_at"))
        ids = row.get("match_id"), row.get("player1_id"), row.get("player2_id")
        if (starts is None or starts <= as_of or any(not isinstance(value, str) or not value for value in ids)
                or ids[0] in seen or ids[1] == ids[2]):
            raise ValueError("Expected unique, upcoming singles fixtures and UTC-aware clocks")
        seen.add(ids[0])
        values = {k: v for k, v in row.items() if k in allowed}
        values["scheduled_at"] = starts
        values["provider_payload"] = {k: row[k] for k in ("bestOf", "deciding_tiebreak", "scoring_rules") if k in row}
        if "scoring_rules" in row:
            rule = row["scoring_rules"]
            clock = timestamp(rule.get("as_of")) if isinstance(rule, dict) else None
            if not clock or clock > as_of:
                raise ValueError("Scoring rules unavailable at snapshot time")
        fixtures.append(MatchRecord(**values))
    return fixtures


def build(history_path, fixtures_path, output):
    payload = json.loads(fixtures_path.read_bytes())
    as_of = timestamp(payload["as_of"])
    if as_of is None:
        raise ValueError("A timezone-aware snapshot as_of is required")
    artifact = json.loads(Path(__file__).with_name("point_calibration_v2.json").read_bytes())
    if as_of <= timestamp(artifact["train_end"]):
        raise ValueError("Calibration unavailable at snapshot time")
    fixtures = fixtures_from_json(payload, as_of)
    # The snapshot's own clock can never authorize using a fixture's result.
    start = perf_counter()
    history, _ = sanitize_history_identities(load_partitions(
        history_path, years=range(as_of.year - 3, as_of.year + 1), before=as_of))
    history, _ = audit_history(history, now=as_of)
    replay = PointHistory(history)
    replay.advance(as_of)
    prepared = perf_counter()
    cards = {}
    for match in fixtures:
        issue = payload.get("candidate_predictions", {}).get(match.match_id, {})
        issued = timestamp(issue.get("as_of"))
        if (issue.get("candidate") != CANDIDATE or issue.get("model_sha256") != MODEL_SHA
                or issue.get("players") != [match.player1_id, match.player2_id]
                or not issued or issued > as_of or issued >= match.scheduled_at):
            raise ValueError(f"Missing valid pre-match candidate for {match.match_id}")
        value = replay.card(match, payload.get("opponent_styles"), candidate=float(issue["p1"]),
                            offsets=artifact["groups"])
        if value:
            cards[match.match_id] = value
    finished = perf_counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            json.dump({"schema": 3, "candidate": CANDIDATE, "cards": cards}, tmp, ensure_ascii=False, allow_nan=False)
        os.replace(tmp_path, output)
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
    return {"fixtures": len(fixtures), "cards": len(cards), "history_seconds": prepared - start,
            "compute_seconds": finished - prepared, "total_seconds": perf_counter() - start}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path, help="Local JSON with as_of and fixtures")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.history, args.fixtures, args.out), indent=2))
