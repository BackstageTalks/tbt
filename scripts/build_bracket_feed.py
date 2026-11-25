"""Build the public draw sidecar from today's offer and existing match-status evidence.

Run with PYTHONPATH=api:scripts. The evidence document contains events (raw
TennisAPI fixtures already seen by the collector) and statuses (verified
match-status rows keyed by native event ID). No fixture lookups are made here.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

OFFER_FIELDS = (
    "upcoming", "prime_picks", "top_daily_picks", "daily_picks",
    "value_picks", "doubles_picks", "ace_picks", "sg_picks",
)
BRATISLAVA = ZoneInfo("Europe/Bratislava")


def native_id(value):
    text = str(value or "")
    return text if re.fullmatch(r"[1-9][0-9]{0,17}", text) else ""


def round_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def matches_on_day(feed, day):
    for field in OFFER_FIELDS:
        for row in feed.get(field) or []:
            fixture = row.get("fixture") or row
            event_id = native_id(row.get("event_id") or fixture.get("event_id") or fixture.get("match_id") or row.get("id"))
            stamp = fixture.get("scheduled_at") or row.get("scheduled_at") or row.get("start_time")
            if not stamp or not event_id:
                continue
            try:
                moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if moment.tzinfo and moment.astimezone(BRATISLAVA).date() == day:
                yield event_id, fixture


def normalize_draws(payload):
    if payload and not isinstance(payload.get("cupTrees"), list):
        raise ValueError("Unrecognized cup-trees response")
    draws = []
    for cup in payload.get("cupTrees", []):
        for index, roots in enumerate(cup.get("views") or []):
            rounds = {}

            def walk(node, depth=0):
                if not node:
                    return
                if depth > 12:
                    raise ValueError("Unexpected draw depth")
                players = []
                for side in ("leftParticipant", "rightParticipant"):
                    participant = node.get(side) or {}
                    team = participant.get("team") or {}
                    players.append({
                        "id": native_id(team.get("id")),
                        "name": str(team.get("name") or "")[:120],
                        "score": str(participant.get("score") if participant.get("score") is not None else "")[:24],
                    })
                winner_id = ""
                if node.get("finished") is True:
                    winners = [player["id"] for side, player in zip(("leftParticipant", "rightParticipant"), players)
                               if (node.get(side) or {}).get("winner") is True and player["id"]]
                    if len(winners) == 1:
                        winner_id = winners[0]
                name = str((node.get("round") or {}).get("description") or "")[:80]
                event_ids = list(dict.fromkeys(filter(None, map(native_id, node.get("eventIds") or []))))
                if name or event_ids or any(player["name"] for player in players):
                    # Multi-event team blocks do not identify a single fixture.
                    rounds.setdefault((depth, name), []).append({
                        "event_id": event_ids[0] if len(event_ids) == 1 else "",
                        "players": players,
                        "winner_id": winner_id,
                    })
                walk(node.get("left"), depth + 1)
                walk(node.get("right"), depth + 1)

            for root in roots:
                walk(root)
            if rounds:
                draws.append({
                    "id": f"{native_id(cup.get('id'))}:{index}",
                    "name": str(cup.get("name") or "")[:160],
                    "rounds": [
                        {"name": name, "matches": matches}
                        for (_, name), matches in sorted(rounds.items(), key=lambda item: -item[0][0])
                    ],
                })
    return draws


def apply_settlement(match, status, event):
    players = match["players"]
    ids = {player["id"] for player in players}
    winner = native_id(status.get("winner_id"))
    home = native_id(status.get("provider_home_id"))
    away = native_id(status.get("provider_away_id"))
    if status.get("status") not in {"win", "loss"} or not winner or len(ids) != 2 or ids != {home, away} or winner not in ids:
        return
    match["winner_id"] = winner
    match["settled_by_worker"] = True
    team_ids = [native_id((event.get(side) or {}).get("id")) for side in ("homeTeam", "awayTeam")]
    if team_ids != [home, away]:
        return
    scores = [event.get(side) or {} for side in ("homeScore", "awayScore")]
    sets = [[score.get(f"period{index}") for score in scores] for index in range(1, 6)]
    appeared = [index for index, pair in enumerate(sets) if any(value is not None for value in pair)]
    if len(appeared) not in {2, 3, 4, 5} or appeared != list(range(len(appeared))):
        return
    complete = sets[:len(appeared)]
    if any(type(a) is not int or type(b) is not int or
           not ((max(a, b) == 6 and 0 <= min(a, b) <= 4) or
                (max(a, b) == 7 and min(a, b) in {5, 6})) for a, b in complete):
        return
    home_wins = sum(a > b for a, b in complete)
    away_wins = len(complete) - home_wins
    if max(home_wins, away_wins) not in {2, 3} or min(home_wins, away_wins) >= max(home_wins, away_wins) or (home_wins > away_wins) != (winner == home):
        return
    for player in players:
        side = 0 if player["id"] == home else 1
        player["score"] = " ".join(str(pair[side]) for pair in complete)


def draw_matches(draws):
    for draw in draws:
        for round_ in draw["rounds"]:
            yield from round_["matches"]


def keep_settlements(draws, previous_draws):
    old = {match["event_id"]: match for match in draw_matches(previous_draws)
           if match.get("settled_by_worker") and match["event_id"]}
    for match in draw_matches(draws):
        previous = old.get(match["event_id"])
        if previous is None:
            continue
        scores = {player["id"]: player["score"] for player in previous["players"]}
        if set(scores) != {player["id"] for player in match["players"]}:
            continue
        match["winner_id"] = previous["winner_id"]
        match["settled_by_worker"] = True
        for player in match["players"]:
            player["score"] = scores[player["id"]] or player["score"]


def build_feed(feed, evidence, previous, day, fetch, limit):
    events = {native_id(row.get("id")): row for row in evidence.get("events", []) if native_id(row.get("id"))}
    statuses = evidence.get("statuses") or {}
    by_tournament = {}
    unresolved = 0
    for event_id, fixture in matches_on_day(feed, day):
        event = events.get(event_id) or fixture.get("provider_payload") or {}
        if native_id(event.get("id")) != event_id:
            unresolved += 1
            continue
        tournament = event.get("tournament") or {}
        unique = tournament.get("uniqueTournament") or {}
        tid = native_id(unique.get("id"))
        sid = native_id((event.get("season") or {}).get("id"))
        if not tid or not sid:
            unresolved += 1
            continue
        key = f"{tid}:{sid}"
        name = str(unique.get("name") or tournament.get("name") or fixture.get("tournament") or "")[:160]
        _, rounds = by_tournament.setdefault(key, (name, set()))
        key_round = round_key((event.get("roundInfo") or {}).get("name") or fixture.get("round_name"))
        if key_round:
            rounds.add(key_round)

    cutoff = (day - timedelta(days=7)).isoformat()
    entries = {item["id"]: item for item in previous.get("tournaments", []) if item["last_seen"] >= cutoff}
    requests = failures = 0
    for key, (name, rounds) in by_tournament.items():
        entry = entries.setdefault(key, {"id": key, "name": name, "draws": [], "seen_rounds": [], "last_seen": day.isoformat()})
        entry["last_seen"] = day.isoformat()
        should_fetch = (not entry["draws"] or rounds.difference(entry["seen_rounds"]))
        if not should_fetch or requests >= limit or entry.get("attempt") == [day.isoformat(), sorted(rounds)]:
            continue
        entry["attempt"] = [day.isoformat(), sorted(rounds)]
        requests += 1
        try:
            draws = normalize_draws(fetch(*key.split(":")) or {})
        except (ValueError, TypeError, AttributeError) as error:
            failures += 1
            print(f"Bracket refresh failed for {key}: {type(error).__name__}")
        else:
            if draws:
                keep_settlements(draws, entry["draws"])
                entry["draws"] = draws
                entry["seen_rounds"] = sorted(set(entry["seen_rounds"]) | rounds)

    for entry in entries.values():
        for match in draw_matches(entry["draws"]):
            eid = match["event_id"]
            if eid in statuses:
                apply_settlement(match, statuses[eid], events.get(eid, {}))
    return {
        "schema": 1, "date": day.isoformat(),
        "tournaments": list(entries.values()),
    }, {"cup_tree_attempts": requests, "cup_tree_errors": failures, "unresolved_offer_rows": unresolved}


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    try:
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("api/data/bracket.json"))
    parser.add_argument("--budget-db", type=Path, default=Path(".cache/bracket-budget.sqlite3"))
    parser.add_argument("--day", type=date.fromisoformat, default=datetime.now(BRATISLAVA).date())
    parser.add_argument("--settlements-only", action="store_true")
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    previous = read(args.output) if args.output.is_file() else {}
    client = budget = None

    def fetch(tid, sid):
        nonlocal client, budget
        from history_download_budget import LocalRequestBudget, RequestBudgetExceeded
        from tbt.errors import ProviderError
        from tbt.providers.rapidapi import RapidTennisClient
        from tbt.providers.shared_budget import SharedBudgetExhausted, SharedBudgetUnavailable, from_environment
        if client is None:
            if from_environment() is None:
                raise SystemExit("Shared API budget configuration required for cup-trees")
            args.budget_db.parent.mkdir(parents=True, exist_ok=True)
            budget = LocalRequestBudget(args.budget_db, limit)
            client = RapidTennisClient(request_budget=budget)
            client.retry_attempts = 1
        try:
            return client._get(f"/api/tennis/tournament/{tid}/season/{sid}/cup-trees", optional_not_found=True)
        except (ProviderError, RequestBudgetExceeded, SharedBudgetExhausted, SharedBudgetUnavailable) as error:
            raise ValueError(type(error).__name__) from error

    limit = 0 if args.settlements_only else int(os.getenv("TBT_BRACKET_MAX_REQUESTS", "30"))
    if not 0 <= limit <= 14500:
        parser.error("TBT_BRACKET_MAX_REQUESTS must be in 0..14500")
    try:
        snapshot, report = build_feed(read(args.feed), read(args.evidence), previous, args.day, fetch, limit)
        write_atomic(args.output, snapshot)
        print(json.dumps(report))
    finally:
        if client is not None:
            client.close()
        if budget is not None:
            budget.close()


if __name__ == "__main__":
    main()
