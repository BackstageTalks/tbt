from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import re
from zoneinfo import ZoneInfo

from tbt.services.match_status import bracket_fixture_context
from tbt.services.media_storage import _blob_service, _container, _container_name
from tbt.match_format import explicit_best_of_from_event
from tbt.services.match_status import classify_finished_event, explicit_actual_start, provider_event_schedule
from tbt.utils import normalize_surface

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
    events = {}
    ambiguous = set()
    for row in evidence.get("events", []):
        event_id = native_id(row.get("id"))
        if not event_id:
            continue
        if event_id in events and events[event_id] != row:
            ambiguous.add(event_id)
        events[event_id] = row
    trusted_events = {eid: event for eid, event in events.items() if eid not in ambiguous}
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
    verified_at = datetime.now(BRATISLAVA)
    for entry in snapshot["tournaments"]:
        matches = [item[3] for item in entry.get("observed_matches", {}).values()]
        matches.extend(draw_matches(entry["draws"]))
        for match in matches:
            event_id = match["event_id"]
            event = trusted_events.get(event_id)
            if event is None and event_id not in ambiguous:
                continue  # retain previously verified context for the same node
            match.pop("analysis_context", None)
            if event is not None and tournament_key(event) == entry["id"]:
                context = bracket_fixture_context(event, match, verified_at)
                if context is not None:
                    match["analysis_context"] = context
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


def load_bracket_snapshot(*, with_revision=False):
    from azure.core.exceptions import ResourceNotFoundError

    with _blob_service() as service:
        blob = service.get_blob_client(_container_name(), "feeds/bracket.json")
        try:
            reader = blob.download_blob()
            snapshot = json.loads(reader.readall())
            return (snapshot, reader.properties.etag) if with_revision else snapshot
        except ResourceNotFoundError:
            return ({}, None) if with_revision else {}


def save_bracket_snapshot(snapshot, *, revision):
    from azure.core import MatchConditions

    options = ({"overwrite": False} if revision is None else
               {"overwrite": True, "etag": revision, "match_condition": MatchConditions.IfNotModified})
    with _container() as container:
        container.get_blob_client("feeds/bracket.json").upload_blob(
            json.dumps(snapshot, ensure_ascii=False), **options,
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


def _instant(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value if value.tzinfo else None
    except ValueError:
        return None


def _pair(match):
    ids = sorted(native_id(p.get("id")) for p in match.get("players", []))
    return ids if len(ids) == 2 and all(ids) and ids[0] != ids[1] else []


def _comparison_context(event):
    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    category = tournament.get("category") or unique.get("category") or {}
    name = str(category.get("name") or "").strip().casefold()
    tour = {
        "atp": "atp", "atp challenger": "atp", "challenger men": "atp",
        "wta": "wta", "wta 125": "wta", "wta challenger": "wta",
    }.get(name)
    surface = normalize_surface(event.get("groundType") or event.get("surface")
                                or tournament.get("groundType") or unique.get("groundType"))
    best_of = explicit_best_of_from_event(event)
    if tour and surface in {"hard", "clay", "grass", "indoor_hard"} and best_of in (3, 5):
        return {"tour": tour, "surface": surface, "best_of": best_of}
    return None


def _offer_prediction(rows, pair):
    candidates = []
    for row in rows:
        ids = sorted(native_id((row.get(side) or {}).get("id")) for side in ("player1", "player2"))
        winner = native_id(row.get("winner_id") or row.get("selection_id"))
        probability = row.get("blinq_probability")
        version = row.get("model_version")
        raw_quality = row.get("quality") or {}
        p1, p2 = (raw_quality.get(side) or {} for side in ("player1", "player2"))
        sample_values = [p1.get("matches"), p2.get("matches"),
                         p1.get("surface_matches"), p2.get("surface_matches")]
        quality = None
        if all(type(value) is int and value >= 0 for value in sample_values):
            a, b, sa, sb = sample_values
            band = ("high" if min(a, b) >= 25 and min(sa, sb) >= 10 else
                    "medium" if min(a, b) >= 10 and min(sa, sb) >= 4 else "low")
            quality = dict(band=band, player1_matches=a, player2_matches=b,
                           player1_surface_matches=sa, player2_surface_matches=sb)
        if (ids == pair and winner in pair and type(probability) in (float, int)
                and 0 <= probability <= 1 and version and quality is not None):
            raw_odds = row.get("odds")
            odds = raw_odds if type(raw_odds) in (float, int) and math.isfinite(raw_odds) and raw_odds > 1 else None
            candidates.append({"predicted_winner_id": winner, "probability": probability,
                               "quality": quality, "model_version": version,
                               "source": "offer", "odds": odds})
    if candidates and all(item == candidates[0] for item in candidates):
        return candidates[0]
    return None


def update_bracket_predictions(snapshot, feed, events, statuses, predict, clock, can_compare):
    offers = {}
    for field in ("top_daily_picks", "daily_picks", "prime_picks", "value_picks"):
        for row in feed.get(field) or []:
            if (str(row.get("market") or "match_winner") == "match_winner"
                    and row.get("publication_status") == "published" and row.get("issued_at")):
                offers.setdefault(native_id(row.get("event_id")), []).append(row)
    for entry in snapshot["tournaments"]:
        records = entry.setdefault("predictions", {})
        for draw in display_draws(entry):
            for round_row in draw["rounds"]:
                for match in round_row["matches"]:
                    eid, pair = native_id(match["event_id"]), _pair(match)
                    if not eid or not pair:
                        continue
                    key = ":".join((eid, *pair))  # edition scopes the enclosing records
                    record = records.get(key)
                    event = events.get(eid) or {}
                    event_verified = native_id(event.get("id")) == eid and tournament_key(event) == entry["id"]
                    if event and not event_verified:
                        continue
                    terminal = statuses.get(eid) or {}
                    if event_verified and (not terminal or not terminal.get("actual_started_at")):
                        terminal = classify_finished_event(
                            {"player1": {"id": pair[0]}, "player2": {"id": pair[1]},
                             "winner_id": pair[0]},
                            event, checked_at=clock(),
                        ) or terminal
                    if record is not None:
                        if sorted(native_id(terminal.get(side)) for side in
                                  ("provider_home_id", "provider_away_id")) != pair:
                            continue
                        status = terminal.get("status")
                        if status in {"retired", "void"}:
                            record["outcome"] = "excluded"
                            continue
                        started = _instant(terminal.get("actual_started_at"))
                        winner = native_id(terminal.get("winner_id"))
                        if status not in {"win", "loss"} or winner not in pair or started is None:
                            continue
                        frozen_at = _instant(record.get("frozen_at"))
                        if frozen_at is None:
                            continue
                        record["outcome"] = (
                            "excluded" if frozen_at >= started else
                            "correct" if winner == record["predicted_winner_id"] else "incorrect"
                        )
                        continue
                    if not event_verified:
                        continue
                    context = match.get("analysis_context") or _comparison_context(event)
                    scheduled = provider_event_schedule(event)
                    event_pair = sorted(native_id((event.get(side) or {}).get("id")) for side in ("homeTeam", "awayTeam"))
                    state = (event.get("status") or {}).get("type")
                    checked = clock()
                    if (terminal or match.get("winner_id") or not scheduled or scheduled <= checked
                            or explicit_actual_start(event) is not None
                            or event_pair != pair or state != "notstarted"):
                        continue
                    candidates = [row for row in offers.get(eid, [])
                                  if (issued := _instant(row["issued_at"])) is not None and issued <= checked]
                    selected = _offer_prediction(candidates, pair)
                    if selected is None and context and can_compare():
                        selected = predict(pair, context)
                    frozen = clock()
                    if selected is None or frozen >= scheduled or selected["predicted_winner_id"] not in pair:
                        continue
                    records[key] = {**selected, "event_id": eid, "player_ids": pair,
                                    "round": str(round_row.get("name") or ""),
                                    "frozen_at": frozen.isoformat(), "outcome": "pending"}


def tournament_stats(entry, draws):
    keys = {":".join((eid, *pair)) for node in draw_matches(draws)
            if (eid := native_id(node["event_id"])) and (pair := _pair(node))}
    rows = [record for key, record in (entry.get("predictions") or {}).items() if key in keys]
    def score(items):
        correct = sum(row["outcome"] == "correct" for row in items)
        incorrect = sum(row["outcome"] == "incorrect" for row in items)
        return correct, incorrect
    good, bad = score(rows)
    waiting = sum(row["outcome"] == "pending" for row in rows)
    total = good + bad
    percent = f"{100 * good / total:.1f}".replace(".", ",") + " %" if total else "—"
    return [
        {"id": "accuracy", "title": "Úspešnosť", "items": [
            {"label": "Správne predikcie", "value": percent, "hint": f"{good} z {total} vyhodnotených"},
        ]},
        {"id": "state", "title": "Stav", "items": [
            {"label": label, "value": value, "hint": ""}
            for label, value in (("Správne", good), ("Nesprávne", bad), ("Čaká", waiting))
        ]},
        {"id": "rounds", "title": "Podľa kôl", "items": [
            {"label": name, "value": f"{hits} z {hits + misses}", "hint": "Správne z vyhodnotených"}
            for name in sorted({row["round"] for row in rows if row["round"]})
            for hits, misses in [score([row for row in rows if row["round"] == name])]
        ]},
    ]


def public_brackets(snapshot, day, *, analysis_allowed=False):
    today = day.isoformat()
    tournaments = []
    for entry in snapshot.get("tournaments", []):
        if entry["last_seen"] != today:
            continue
        draws = display_draws(entry)
        item = {"id": entry["id"], "name": entry["name"], "draws": draws}
        for match in draw_matches(draws):
            if analysis_allowed:
                key = ":".join((match["event_id"], *_pair(match)))
                prediction = (entry.get("predictions") or {}).get(key)
                if prediction:
                    match["prediction"] = {k: deepcopy(v) for k, v in prediction.items() if k != "odds"}
            else:
                match.pop("analysis_context", None)
        if analysis_allowed:
            item["tournament_stats"] = tournament_stats(entry, draws)
        tournaments.append(item)
    return {"schema": 1, "date": today, "tournaments": tournaments}
