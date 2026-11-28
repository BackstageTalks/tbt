"""Settlement of private, pre-match point cards using already observed events."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

from . import point_model_shadow
from .match_status import classify_finished_event, explicit_actual_start, provider_event_schedule
from ..models.point_rules import completed_set

LEVELS = ("ATP", "WTA", "Challenger", "WTA 125")
PARTITION = "point-model-shadow-v3"


def outcome(card, event, now):
    p1, p2 = card["players"]
    row = {"player1": {"id": p1}, "player2": {"id": p2}, "selection_id": p1}
    classified = classify_finished_event(row, event, checked_at=now)
    if not classified or classified["status"] not in {"win", "loss"}:
        return None
    if any(marker in classified["provider_status"] for marker in ("abandon", "interrupt", "default", "suspend", "walk-over")):
        return None
    frozen = datetime.fromisoformat(card["frozen_at"])
    scheduled = datetime.fromisoformat(card["scheduled_at"])
    observed = explicit_actual_start(event) or provider_event_schedule(event) or scheduled
    if not frozen < min(observed, scheduled) or observed > now:
        return None
    scores = [event.get(k) or {} for k in ("homeScore", "awayScore")]
    if classified["provider_home_id"] != p1:
        scores.reverse()
    rules = card["scoring_rules"]
    wins, games, tiebreak = [0, 0], [0, 0], False
    target = card["best_of"] // 2 + 1
    for index in range(1, 6):
        pair = [s.get(f"period{index}") for s in scores]
        if pair == [None, None]:
            if any(s.get(f"period{i}") is not None for s in scores for i in range(index+1, 6)):
                return None
            break
        if any(not str(v).isascii() or not str(v).isdigit() for v in pair) or max(wins) >= target:
            return None
        a, b = map(int, pair)
        hi, lo = max(a,b), min(a,b)
        if rules["match_tiebreak"] and index == card["best_of"]:
            if not ((hi, lo) == (1, 0) or hi == 10 and lo <= 8 or hi > 10 and hi-lo == 2):
                return None
            tiebreak = True
            a, b = int(a>b), int(b>a)
        else:
            if not completed_set(a, b, rules["short"]):
                return None
            tiebreak |= (hi, lo) == ((4, 3) if rules["short"] else (7, 6))
        wins[int(b>a)] += 1
        games[0] += a
        games[1] += b
    if max(wins) != target or (wins[0]>wins[1]) != (classified["winner_id"] == p1):
        return None
    if any(s.get("current") is not None and str(s["current"]) != str(w) for s,w in zip(scores,wins)):
        return None
    return {"set_score": f"{wins[0]}:{wins[1]}", "games": sum(games),
            "margin_p1": games[0]-games[1], "tiebreak": tiebreak}


def markets(card, actual):
    projections = card["other_projections"]["value"]
    for score, prob in card["set_score"]["value"].items():
        yield "set " + score, prob, actual["set_score"] == score
    for line, sides in projections["totals"].items():
        for side, prob in sides.items():
            yield f"{side} {line}", prob, (actual["games"] > float(line)) == (side == "over")
    for line, probs in projections["handicap"].items():
        for i, prob in enumerate(probs):
            margin = actual["margin_p1"] * (1 if i == 0 else -1)
            yield f"P{i+1} {line}", prob, margin + float(line) > 0
    yield "tiebreak", projections["tiebreak"], actual["tiebreak"]


def recent_records(table, since, now):
    month = since.date().replace(day=1)
    while month <= now.date():
        partition = f"{PARTITION}-{month:%Y-%m}"
        for row in table.query_entities(f"PartitionKey eq '{partition}'"):
            if since <= datetime.fromisoformat(row["scheduled"]) <= now:
                yield row
        month = (month + timedelta(days=32)).replace(day=1)


def settle(events):
    from azure.core.exceptions import ResourceExistsError
    from .admin_storage import UI_TABLE, _StorageWriteConflict, _table

    cards = point_model_shadow.snapshot_cards()
    table = None
    known = set()
    now = datetime.now(timezone.utc)
    for card in cards.values():
        eid = card.get("event_id")
        if eid not in events:
            continue
        actual = outcome(card, events[eid], now)
        if actual is None:
            continue
        if table is None:
            table = _table(UI_TABLE)
            known = {r["event_id"] for r in recent_records(table, now - timedelta(days=15), now)}
        if eid in known:
            continue
        record = {"PartitionKey": PARTITION + "-" + card["scheduled_at"][:7], "RowKey": sha256(eid.encode()).hexdigest(),
                  "event_id": eid, "scheduled": card["scheduled_at"], "level": card["competition"],
                  "frozen_at": card["frozen_at"], "model_version": card["model_version"],
                  "calibration_version": card["calibration_version"], **actual,
                  "markets": json.dumps(list(markets(card, actual)), allow_nan=False)}
        try:
            table.create_entity(record)
        except (ResourceExistsError, _StorageWriteConflict):
            pass


def summarize(records):
    samples = defaultdict(list)
    counts = dict.fromkeys(LEVELS, 0)
    count = 0
    for record in records:
        count += 1
        counts[record["level"]] += 1
        for market, p, y in json.loads(record["markets"]):
            for group in ("Spolu", record["level"]):
                samples[group, market].append((p, int(y)))
    rows = []
    for (group, market), values in sorted(samples.items()):
        bins = defaultdict(float)
        for p, y in values:
            bins[min(9, int(10*p))] += p-y
        n = len(values)
        rows.append({"level": group, "market": market, "n": n,
                     "ece": sum(map(abs, bins.values()))/n,
                     "brier": sum((p-y)**2 for p,y in values)/n})
    return {"count": count, "levels": counts, "days": 90, "checkpoint": 300, "rows": rows}


def rolling():
    from .admin_storage import UI_TABLE, _table
    now = datetime.now(timezone.utc)
    return summarize(recent_records(_table(UI_TABLE), now - timedelta(days=90), now))
