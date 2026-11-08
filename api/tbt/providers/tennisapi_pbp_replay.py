"""Read-only TennisApi point tape replay; never creates CDB/model features.

The provider commonly omits the terminal (game-winning) point. Replay that
winner only when every visible score transition, game winner/server and set
score are internally consistent. A missing provider event ID or missing match
score witness remains unverified identity, not import authorization.
"""
from __future__ import annotations

from collections import Counter

from ..errors import ProviderError


_SCORE = {"0", "15", "30", "40", "A"}


def _next_point(score: tuple[str, str], winner: int):
    home, away = score
    if home not in _SCORE or away not in _SCORE or (home == away == "A"):
        raise ProviderError("Invalid point score")
    if home == "A" and away != "40" or away == "A" and home != "40":
        raise ProviderError("Invalid advantage score")
    if winner == 1:
        if home == "A" or (home == "40" and away in {"0", "15", "30"}):
            return None
        if home == "40" and away == "A":
            return ("40", "40")
        if home == "40" and away == "40":
            return ("A", "40")
        return ({"0": "15", "15": "30", "30": "40"}[home], away)
    if winner == 2:
        if away == "A" or (away == "40" and home in {"0", "15", "30"}):
            return None
        if away == "40" and home == "A":
            return ("40", "40")
        if away == "40" and home == "40":
            return ("40", "A")
        return (home, {"0": "15", "15": "30", "30": "40"}[away])
    raise ProviderError("Unknown point winner")


def _observed_transition(before, after):
    candidates = []
    for side in (1, 2):
        if _next_point(before, side) == after:
            candidates.append(side)
    if len(candidates) != 1:
        raise ProviderError("Inconsistent point tape transition")
    return candidates[0]


def replay_point_by_point(payload, *, event_id, expected_sets=None):
    """Replay completed ordinary tennis games for *research only*.

    `expected_sets` is an independently matched event's sequence of
    (home_games, away_games). It does not itself certify the original API
    request URL, player identity, tie-breaks, or source completeness.
    Unsupported tie-break score notation fails closed.
    """
    if not isinstance(payload, dict):
        raise ProviderError("Point-by-point replay requires object envelope")
    claimed = payload.get("eventId", payload.get("event_id"))
    if claimed is not None and str(claimed) != str(event_id):
        raise ProviderError("Point-by-point event ID mismatch")
    sets = payload.get("pointByPoint", payload.get("sets"))
    if not isinstance(sets, list) or not 0 < len(sets) <= 5:
        raise ProviderError("Missing point-by-point set tape")
    expected = None
    if expected_sets is not None:
        if not isinstance(expected_sets, (list, tuple)) or len(expected_sets) != len(sets):
            raise ProviderError("Expected finished match set count mismatch")
        expected = []
        for score in expected_sets:
            if (not isinstance(score, (list, tuple)) or len(score) != 2
                    or any(type(v) is not int or v < 0 or v > 13 for v in score)):
                raise ProviderError("Invalid external set score witness")
            expected.append(tuple(score))

    seen = set()
    total = Counter()
    per_set = {}
    for set_row in sets:
        if not isinstance(set_row, dict):
            raise ProviderError("Malformed PBP set")
        number = set_row.get("set")
        if type(number) is not int or not 1 <= number <= 5 or number in seen:
            raise ProviderError("Ambiguous PBP set number")
        seen.add(number)
        games = set_row.get("games")
        if not isinstance(games, list) or not 0 < len(games) <= 50:
            raise ProviderError("Incomplete PBP game list")
        indexed = {}
        for g in games:
            if not isinstance(g, dict) or type(g.get("game")) is not int:
                raise ProviderError("Invalid PBP game identifier")
            n = g["game"]
            if n in indexed or not 1 <= n <= 50:
                raise ProviderError("Duplicate/out-of-range PBP game")
            indexed[n] = g
        if sorted(indexed) != list(range(1, len(indexed) + 1)):
            raise ProviderError("Gapped PBP game tape")

        result = Counter()
        scoreboard = [0, 0]
        last_server = None
        for game_num in sorted(indexed):
            game = indexed[game_num]
            score = game.get("score")
            points = game.get("points")
            if not isinstance(score, dict) or not isinstance(points, list) or not points:
                raise ProviderError("Missing PBP points/server/winner")
            server, game_winner = score.get("serving"), score.get("scoring")
            if type(server) is not int or type(game_winner) is not int or (
                    server not in (1, 2) or game_winner not in (1, 2)):
                raise ProviderError("PBP game server/winner not explicit")
            if last_server == server:
                raise ProviderError("Non-alternating PBP server (unsupported tie-break)")
            last_server = server
            state = ("0", "0")
            receiver = 3 - server

            def record_point(winner, *, inferred=False):
                result["points"] += 1
                result[f"p{winner}_points_won"] += 1
                result[f"p{server}_{'service' if winner == server else 'return'}_points_won"] += 1 if winner == server else 0
                if winner != server:
                    result[f"p{winner}_return_points_won"] += 1
                result[f"p{server}_service_points_played"] += 1
                if _next_point(state, receiver) is None:
                    result[f"p{receiver}_bp_chances"] += 1
                    result[f"p{server}_bp_faced"] += 1
                    if winner == receiver:
                        result[f"p{receiver}_bp_converted"] += 1
                    else:
                        result[f"p{server}_bp_saved"] += 1
                if inferred:
                    result["inferred_terminal_points"] += 1

            for point in points:
                if not isinstance(point, dict):
                    raise ProviderError("Malformed PBP point")
                next_state = (str(point.get("homePoint")), str(point.get("awayPoint")))
                winner = _observed_transition(state, next_state)
                record_point(winner)
                state = next_state
                result["observed_points"] += 1
            if _next_point(state, game_winner) is not None:
                raise ProviderError("Missing more than the terminal game point")
            record_point(game_winner, inferred=True)
            scoreboard[game_winner - 1] += 1
            if (score.get("homeScore"), score.get("awayScore")) != tuple(scoreboard):
                raise ProviderError("PBP game score contradicts game winner")
            result["games"] += 1
            result[f"p{game_winner}_games_won"] += 1
            if game_winner != server:
                result[f"p{game_winner}_break_games_won"] += 1
        if expected is not None:
            if number > len(expected) or tuple(scoreboard) != expected[number - 1]:
                raise ProviderError("PBP score differs from independently attested match")
        per_set[str(number)] = dict(sorted(result.items()))
        total.update(result)
        total["sets"] += 1
    if seen != set(range(1, len(seen) + 1)):
        raise ProviderError("Gapped set tape")
    if expected is not None and len(seen) != len(expected):
        raise ProviderError("Incomplete match set tape")
    return {
        "schema": 1, "event_id": str(event_id),
        "provider_event_id_present": claimed is not None,
        "match_score_witness_attested": expected is not None,
        "source": "tennisapi1", "quality_status": (
            "score_replayed_requires_identity_witness" if expected is not None
            else "tape_replayed_no_external_score_witness"
        ),
        "counts": dict(sorted(total.items())), "sets": per_set,
        "eligible_for_cdb_point_features": False,
        "production_mutated": False,
        "provider_requests": 0,
    }
