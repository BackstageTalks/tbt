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


def capture_morning(upcoming, predictions, candidate_path, history_dir, sg_context=None):
    """Use only the already downloaded model, schedule, predictions and history."""
    from datetime import datetime, timedelta, timezone
    from hashlib import sha256
    from tempfile import TemporaryDirectory
    from zoneinfo import ZoneInfo
    from tbt.models.point_model import competition
    from tbt.match_format import explicit_best_of_from_event
    from tbt.services.engine import event_id
    from point_shadow_blob import publish

    if sha256(candidate_path.read_bytes()).hexdigest() != MODEL_SHA:
        raise ValueError("Frozen candidate unavailable")
    clock = datetime.now(timezone.utc)
    zone = ZoneInfo("Europe/Bratislava")
    today = clock.astimezone(zone).date()
    pending = {m.match_id: m for m in upcoming if competition(m) in {"ATP", "WTA", "Challenger", "WTA 125"}
               and not m.is_completed and m.status in {"upcoming", "notstarted", "scheduled"}
               and m.scheduled_at > clock and today <= m.scheduled_at.astimezone(zone).date() <= today + timedelta(days=1)}
    fixtures, issues, events = [], {}, {}
    for row in predictions:
        match = pending.get(row["id"])
        if not match or match.match_id in issues:
            continue
        ids = [row[k]["id"] for k in ("player1", "player2")]
        if (ids != [match.player1_id, match.player2_id] or row["event_id"] != event_id(match)
                or timestamp(row["scheduled_at"]) != match.scheduled_at):
            continue
        fixture = {f.name: getattr(match, f.name) for f in fields(MatchRecord)
                   if f.name not in ("provider_payload", "stats", "scheduled_at")}
        fixture["scheduled_at"] = match.scheduled_at.isoformat()
        for key in ("bestOf", "deciding_tiebreak", "scoring_rules"):
            if key in match.provider_payload:
                fixture[key] = match.provider_payload[key]
        best = explicit_best_of_from_event(match.provider_payload) or match.best_of
        if best in (3, 5):
            fixture["bestOf"] = best
        fixtures.append(fixture)
        issues[match.match_id] = {"candidate": CANDIDATE, "model_sha256": MODEL_SHA, "players": ids,
                                  "as_of": row["created_at"], "p1": row["player1"]["probability"]}
        events[match.match_id] = row["event_id"]
    with TemporaryDirectory() as directory:
        source, output = Path(directory)/"inputs.json", Path(directory)/"snapshot.json"
        source.write_text(json.dumps({"as_of": clock.isoformat(), "fixtures": fixtures,
                                      "candidate_predictions": issues}), encoding="utf-8")
        if fixtures:
            build(history_dir, source, output)
        cards = json.loads(output.read_bytes())["cards"] if fixtures else {}
    frozen = datetime.now(timezone.utc)
    calibration = sha256(Path(__file__).with_name("point_calibration_v2.json").read_bytes()).hexdigest()
    cards = {key: dict(card, event_id=events[key], frozen_at=frozen.isoformat(),
                       source_commit=os.getenv("GITHUB_SHA"),
                       model_version="point-model-v2:" + CANDIDATE, calibration_version=calibration)
             for key, card in cards.items() if timestamp(card["scheduled_at"]) > frozen}
    if sg_context:
        from tbt.services.point_sg import freeze
        offer, fresh, primary, alternatives, floors = sg_context
        def receipt_key(row):
            return tuple(row.get(k) for k in ("event_id", "selection_id", "captured_at", "odds",
                                               "odds_bookmaker", "odds_source"))
        receipts = {receipt_key(row) for row in fresh}
        by_event = {card["event_id"]: card for card in cards.values()}
        for row in offer:
            eid, market = str(row.get("event_id")), row.get("market")
            card = by_event.get(eid)
            if card and receipt_key(row) in receipts and floors.get(market) is not None:
                result = freeze(card, row, primary.get(eid), alternatives.get(eid, {}).get(market, {}),
                                floors[market], frozen)
                completed = datetime.now(timezone.utc)
                if result and completed < timestamp(card["scheduled_at"]):
                    result["frozen_at"] = completed.isoformat()
                    card.setdefault("sg_shadow", {})[market] = result
    publish(cards)
    return {"eligible": len(pending), "computed_before_start": len(cards)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path, help="Local JSON with as_of and fixtures")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.history, args.fixtures, args.out), indent=2))
