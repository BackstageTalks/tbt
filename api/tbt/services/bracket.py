from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
import re
from zoneinfo import ZoneInfo

from tbt.services.media_storage import _blob_service, _container, _container_name

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


# Keep qualifying and doubles separate from the singles knockout.
KNOCKOUT_ROUNDS = {
    "roundof128": 0, "roundof64": 1, "roundof32": 2, "roundof16": 3,
    "quarterfinal": 4, "quarterfinals": 4,
    "semifinal": 5, "semifinals": 5,
    "final": 6,
}


def tournament_key(event):
    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    tid = native_id(unique.get("id"))
    sid = native_id((event.get("season") or {}).get("id"))
    return f"{tid}:{sid}" if tid and sid else ""


def observed_match(event):
    event_id = native_id(event.get("id"))
    teams = [event.get(side) or {} for side in ("homeTeam", "awayTeam")]
    if not event_id or any(not native_id(team.get("id")) or not team.get("name") for team in teams):
        return None
    players = [{"id": native_id(team["id"]), "name": str(team["name"])[:120], "score": ""} for team in teams]
    if players[0]["id"] == players[1]["id"]:
        return None
    match = {"id": event_id, "parent_id": "", "event_id": event_id, "players": players, "winner_id": ""}
    winner_code = event.get("winnerCode")
    if (event.get("status") or {}).get("type") == "finished" and type(winner_code) is int and winner_code in (1, 2):
        winner = players[winner_code - 1]["id"]
        apply_settlement(match, {
            "status": "win", "winner_id": winner,
            "provider_home_id": players[0]["id"], "provider_away_id": players[1]["id"],
        }, event)
    tournament = event.get("tournament") or {}
    name = str(tournament.get("name") or "")[:160]
    group_id = native_id(tournament.get("id")) or name.casefold()
    if not group_id:
        return None
    round_name = str((event.get("roundInfo") or {}).get("name") or "")[:80]
    return group_id, name, round_name, match


def observed_draws(matches):
    groups = {}
    for group_id, name, round_name, source in matches.values():
        group_name, rounds = groups.setdefault(group_id, (name, {}))
        key = round_key(round_name)
        stage = KNOCKOUT_ROUNDS.get(key)
        rounds.setdefault((stage, "" if stage is not None else key), {
            "name": round_name, "matches": [],
        })["matches"].append({**source, "parent_id": ""})

    draws = []
    for key, (name, rounds) in groups.items():
        semifinals = rounds.get((5, ""), {}).get("matches", [])
        semifinal_players = {player["id"] for match in semifinals for player in match["players"]}
        if len(semifinals) == 2 and len(semifinal_players) == 4 and (6, "") not in rounds:
            # The two semifinals determine the final even before its fixture ID exists.
            finalists = [
                next((player for player in match["players"] if player["id"] == match["winner_id"]), {})
                for match in semifinals
            ]
            rounds[6, ""] = {"name": "Final", "matches": [{
                "id": "final-slot", "event_id": "", "parent_id": "",
                "players": [{**player, "score": ""} for player in finalists],
                "winner_id": "", "pending_slot": True,
            }]}
            for match in semifinals:
                match["parent_id"] = "final-slot"

        ordered = sorted(rounds, key=lambda slot: (slot[0] is not None, slot[0] or 0, slot[1]))
        for stage, label in ordered:
            if stage is None:
                continue
            following = rounds.get((stage + 1, ""))
            if not following:
                continue
            for match in rounds[stage, label]["matches"]:
                winner = match["winner_id"]
                if not winner:
                    continue
                parents = [parent for parent in following["matches"]
                           if winner in {player["id"] for player in parent["players"]}]
                if len(parents) == 1:
                    match["parent_id"] = parents[0]["id"]
        draws.append({
            "id": f"observed:{key}", "name": name, "partial": True,
            "rounds": [rounds[slot] for slot in ordered],
        })
    return draws


def normalize_draws(payload):
    if payload and not isinstance(payload.get("cupTrees"), list):
        raise ValueError("Unrecognized cup-trees response")
    draws = []
    for cup in payload.get("cupTrees", []):
        for index, roots in enumerate(cup.get("views") or []):
            rounds = {}

            def walk(node, key, parent_id="", depth=0):
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
                        "id": key,
                        "parent_id": parent_id,
                        "event_id": event_ids[0] if len(event_ids) == 1 else "",
                        "players": players,
                        "winner_id": winner_id,
                    })
                walk(node.get("left"), f"{key}.1", key, depth + 1)
                walk(node.get("right"), f"{key}.2", key, depth + 1)

            for root_index, root in enumerate(roots):
                walk(root, str(root_index))
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
        events.setdefault(event_id, event)
        key = tournament_key(event)
        if not key:
            unresolved += 1
            continue
        name = str(unique.get("name") or tournament.get("name") or fixture.get("tournament") or "")[:160]
        _, rounds = by_tournament.setdefault(key, (name, set()))
        key_round = round_key((event.get("roundInfo") or {}).get("name") or fixture.get("round_name"))
        if key_round:
            rounds.add(key_round)

    cutoff = (day - timedelta(days=7)).isoformat()
    entries = {item["id"]: item for item in previous.get("tournaments", []) if item["last_seen"] >= cutoff}
    today = day.isoformat()
    for key, (name, rounds) in by_tournament.items():
        entry = entries.setdefault(key, {"id": key, "name": name, "draws": [], "seen_rounds": []})
        pending = entry.get("pending_rounds", []) if entry.get("last_seen") == today else []
        entry["last_seen"] = today
        entry["pending_rounds"] = sorted(set(pending) | rounds)

    for event_id, event in events.items():
        entry = entries.get(tournament_key(event))
        if not entry or entry["last_seen"] != today:
            continue
        candidate = observed_match(event)
        if not candidate:
            continue
        observed = entry.setdefault("observed_matches", {})
        prior = observed.get(event_id)
        if prior:
            previous_match = prior[3]
            new_match = candidate[3]
            previous_players = {player["id"]: player for player in previous_match["players"]}
            if previous_players.keys() == {player["id"] for player in new_match["players"]}:
                if previous_match["winner_id"] and not new_match["winner_id"]:
                    continue
                if previous_match["winner_id"] == new_match["winner_id"]:
                    for player in new_match["players"]:
                        player["score"] = player["score"] or previous_players[player["id"]]["score"]
        observed[event_id] = candidate

    requests = failures = 0
    active = sorted(
        (entry for entry in entries.values() if entry["last_seen"] == today),
        key=lambda entry: entry.get("last_attempt_at", ""),
    )
    for entry in active:
        rounds = entry.get("pending_rounds", [])
        attempt = [today, rounds]
        previous_attempt = entry.get("attempt") or []
        should_fetch = (
            not entry["draws"] or set(rounds).difference(entry["seen_rounds"])
            or previous_attempt[:1] != [today]
        )
        if not should_fetch or requests >= limit or entry.get("attempt") == attempt:
            continue
        requests += 1
        entry["last_attempt_at"] = datetime.now(BRATISLAVA).isoformat()
        try:
            draws = normalize_draws(fetch(*entry["id"].split(":")) or {})
        except (ValueError, TypeError, AttributeError) as error:
            failures += 1
            print(f"Bracket refresh failed for {entry['id']}: {type(error).__name__}")
        else:
            entry["attempt"] = attempt
            if draws:
                keep_settlements(draws, entry["draws"])
                entry["draws"] = draws
                entry["seen_rounds"] = sorted(set(entry["seen_rounds"]) | set(rounds))

    snapshot = {"schema": 1, "date": day.isoformat(), "tournaments": list(entries.values())}
    settle_draws(snapshot, statuses, events)
    return snapshot, {
        "cup_tree_attempts": requests, "cup_tree_errors": failures, "unresolved_offer_rows": unresolved,
    }


def settle_draws(snapshot, statuses, events):
    for entry in snapshot["tournaments"]:
        matches = [item[3] for item in entry.get("observed_matches", {}).values()]
        matches.extend(draw_matches(entry["draws"]))
        for match in matches:
            event_id = match["event_id"]
            if event_id in statuses:
                apply_settlement(match, statuses[event_id], events.get(event_id, {}))


def load_bracket_snapshot():
    from azure.core.exceptions import ResourceNotFoundError

    with _blob_service() as service:
        blob = service.get_blob_client(_container_name(), "feeds/bracket.json")
        try:
            return json.loads(blob.download_blob().readall())
        except ResourceNotFoundError:
            return {}


def save_bracket_snapshot(snapshot):
    with _container() as container:
        container.upload_blob(
            "feeds/bracket.json", json.dumps(snapshot, ensure_ascii=False), overwrite=True,
        )


def display_draws(entry):
    observed = entry.get("observed_matches", {})
    if not entry["draws"]:
        return observed_draws(observed)
    draws = deepcopy(entry["draws"])
    for match in draw_matches(draws):
        candidate = observed.get(match["event_id"])
        if not candidate:
            continue
        fixture = candidate[3]
        known = {player["id"]: player for player in fixture["players"]}
        if known.keys() != {player["id"] for player in match["players"]}:
            continue
        for player in match["players"]:
            source = known[player["id"]]
            player["name"] = player["name"] or source["name"]
            player["score"] = player["score"] or source["score"]
        match["winner_id"] = match["winner_id"] or fixture["winner_id"]
    return draws


def public_brackets(snapshot, day):
    today = day.isoformat()
    tournaments = [
        {"id": entry["id"], "name": entry["name"], "draws": display_draws(entry)}
        for entry in snapshot.get("tournaments", [])
        if entry["last_seen"] == today
    ]
    return {"schema": 1, "date": today, "tournaments": tournaments}
