"""Exact absorbing chains for advantage games and standard tiebreak sets."""
from collections import defaultdict
from functools import lru_cache
from heapq import heappop, heappush
from math import comb, isfinite

from .point_rules import STANDARD

TOTAL_LINES = (19.5, 20.5, 21.5)
HANDICAP_LINES = (-3.5, -1.5, 1.5, 3.5)


def game(p, no_ad=False):
    q = 1 - p
    deuce = 20 * p**3 * q**3
    split = 2 * p * q
    early_win = sum(comb(3 + k, k) * p**4 * q**k for k in range(3))
    early_length = sum((4 + k) * comb(3 + k, k) * (p**4 * q**k + q**4 * p**k)
                       for k in range(3))
    if no_ad:
        return early_win + deuce * p, early_length + 7 * deuce
    return early_win + deuce * p*p / (1 - split), early_length + deuce * (6 + 2 / (1 - split))


def tiebreak(points, first, target):
    """Return P(player 1 wins) and expected points served by each player."""
    states = {(0, 0): 1.0}
    won, served = 0.0, [0.0, 0.0]
    for index in range(2 * target - 1):
        server = first ^ (((index + 1) // 2) % 2)
        p = points[0] if server == 0 else 1 - points[1]
        next_states = defaultdict(float)
        for (a, b), mass in states.items():
            if a == b == target - 1:
                # Every two points after equality contain one serve each.
                win = points[0] * (1 - points[1])
                loss = (1 - points[0]) * points[1]
                won += mass * win / (win + loss)
                served[0] += mass / (win + loss)
                served[1] += mass / (win + loss)
                continue
            served[server] += mass
            if a + 1 == target:
                won += mass * p
            else:
                next_states[a + 1, b] += mass * p
            if b + 1 < target:
                next_states[a, b + 1] += mass * (1 - p)
        states = next_states
    return won, served


@lru_cache(maxsize=4096)
def _set(points, first, target, rules=STANDARD, deciding=False):
    if rules.match_tiebreak and deciding:
        win, served = tiebreak(points, first, 10)
        return {(1,0):win, (0,1):1-win}, served, (0.,0.)
    tie_at = 3 if rules.short else 6
    games_to_win = 4 if rules.short else 6
    states = {(0, 0): 1.0}
    scores = {}
    served, breaks = [0.0, 0.0], [0.0, 0.0]
    holds = tuple(game(p, rules.no_ad) for p in points)
    for index in range(2 * tie_at + 1):
        server = first ^ (index % 2)
        next_states = defaultdict(float)
        for (a, b), mass in states.items():
            if a == b == tie_at:
                win, lengths = tiebreak(points, server, target)
                scores[tie_at+1, tie_at], scores[tie_at, tie_at+1] = mass * win, mass * (1 - win)
                for player in (0, 1):
                    served[player] += mass * lengths[player]
                continue
            hold, length = holds[server]
            served[server] += mass * length
            breaks[1 - server] += mass * (1 - hold)
            p = hold if server == 0 else 1 - hold
            for x, y, probability in ((a + 1, b, p), (a, b + 1, 1 - p)):
                if max(x, y) >= games_to_win and abs(x - y) >= 2:
                    scores[x, y] = scores.get((x, y), 0.0) + mass * probability
                else:
                    next_states[x, y] += mass * probability
        states = next_states
    return scores, served, breaks


@lru_cache(maxsize=1024)
def _simulate_cached(points, best_of, deciding_tiebreak, rules):
    need = best_of // 2 + 1
    # The next server is carried across sets, including after a tiebreak.
    # Each histogram is propagated separately because the API uses marginals.
    states = {(0, 0, server): ({0: .5}, {0: .5}, .5, (0., 0.)) for server in (0, 1)}
    sets, total, margin = defaultdict(float), defaultdict(float), defaultdict(float)
    no_tiebreak, first_win = 0.0, [0.0, 0.0]
    comebacks, served, breaks = [0., 0.], [0., 0.], [0., 0.]
    exact_sets = []
    for index in range(best_of):
        transitions = {}
        exact = defaultdict(float)
        for (a, b, server), (games, differences, without_tb, first) in states.items():
            deciding = a == b == need - 1
            scores, lengths, set_breaks = _set(points, server, deciding_tiebreak if deciding else 7, rules, deciding)
            reach = sum(games.values())
            for player in (0, 1):
                served[player] += reach * lengths[player]
                breaks[player] += reach * set_breaks[player]
            for (x, y), prob in scores.items():
                exact[x, y] += reach * prob
                winner = int(y > x)
                s1, s2 = a + (winner == 0), b + (winner == 1)
                length = x + y
                has_tb = (rules.match_tiebreak and deciding) or length == (7 if rules.short else 13)
                first_mass = first if index else (reach * (winner == 0), reach * (winner == 1))
                if index == 0:
                    first_win[winner] += reach * prob
                no_tb_mass = 0. if has_tb else without_tb * prob
                terminal = max(s1, s2) == need
                if terminal:
                    sets[s1, s2] += reach * prob
                    no_tiebreak += no_tb_mass
                    comebacks[winner] += first_mass[1 - winner] * prob
                    dest_games, dest_diff = total, margin
                else:
                    key = s1, s2, server ^ (length % 2)
                    dest = transitions.setdefault(key, [defaultdict(float), defaultdict(float), 0., [0., 0.]])
                    dest_games, dest_diff = dest[:2]
                    dest[2] += no_tb_mass
                    for player in (0, 1):
                        dest[3][player] += first_mass[player] * prob
                for value, mass in games.items():
                    dest_games[value + length] += mass * prob
                for value, mass in differences.items():
                    dest_diff[value + x - y] += mass * prob
        states = transitions
        reach = sum(exact.values())
        if reach:
            ranked = sorted(exact.items(), key=lambda item: (-item[1], item[0]))
            exact_sets.append({"set": index + 1, "played_probability": reach,
                               "top": [{"score": f"{x}:{y}", "probability_if_played": mass / reach}
                                       for (x, y), mass in ranked[:3]]})
    winner_p = tuple(sum(mass for s, mass in sets.items() if s[player] == need) for player in (0, 1))
    at_least_one = tuple(sum(mass for s, mass in sets.items() if s[player]) for player in (0, 1))
    return {
        "winner": winner_p,
        "set_score": {f"{a}:{b}": mass for (a, b), mass in sorted(sets.items())},
        "exact_sets": exact_sets,
        "exact_match_top3": _top_match_scores(points, need, deciding_tiebreak, rules),
        "total_games": dict(sorted(total.items())),
        "game_margin_player1": dict(sorted(margin.items())),
        "totals": {str(line): {"over": sum(m for g, m in total.items() if g > line),
                               "under": sum(m for g, m in total.items() if g < line)}
                   for line in TOTAL_LINES},
        "handicap": {f"{line:+g}": (sum(m for g, m in margin.items() if g + line > 0),
                                   sum(m for g, m in margin.items() if -g + line > 0))
                     for line in HANDICAP_LINES},
        "tiebreak": min(1., max(0., 1 - no_tiebreak)),
        "at_least_one_set": at_least_one,
        "first_set": tuple(first_win),
        "comeback_given_first_set_loss": tuple(comebacks[i] / first_win[1 - i] for i in (0, 1)),
        "service_points": tuple(served),
        "breaks": tuple(breaks),
    }


def _top_match_scores(points, need, deciding_tiebreak, rules):
    @lru_cache(maxsize=None)
    def edges(a, b, server):
        target = deciding_tiebreak if a == b == need - 1 else 7
        return _set(points, server, target, rules, a == b == need - 1)[0]

    @lru_cache(maxsize=None)
    def best_tail(a, b, server):
        if max(a, b) == need:
            return 1.
        return max(p * best_tail(a + (x > y), b + (y > x), server ^ ((x + y) % 2))
                   for (x, y), p in edges(a, b, server).items())

    def bound(a, b, server, p, q):
        return p * best_tail(a, b, server) + q * best_tail(a, b, 1 - server)

    queue = [(-bound(0, 0, 0, .5, .5), (), 0, 0, 0, .5, .5)]
    top = []
    while queue and len(top) < 3:
        _, path, a, b, server, p, q = heappop(queue)
        if max(a, b) == need:
            top.append({"scores": [f"{x}:{y}" for x, y in path], "probability": p + q})
            continue
        reverse = edges(a, b, 1 - server)
        for (x, y), prob in edges(a, b, server).items():
            s1, s2 = a + (x > y), b + (y > x)
            following = server ^ ((x + y) % 2)
            left, right = p * prob, q * reverse[x, y]
            heappush(queue, (-bound(s1, s2, following, left, right), path + ((x, y),),
                             s1, s2, following, left, right))
    return top


def simulate(p1, p2, best_of=3, deciding_tiebreak=7, rules=STANDARD):
    """Equal pre-match chance to serve first. Counts 7:6 as 13 games."""
    from copy import deepcopy

    if best_of not in (3, 5) or deciding_tiebreak not in (7, 10):
        raise ValueError("Unsupported singles format")
    if not all(isfinite(p) and 0.01 <= p <= 0.99 for p in (p1, p2)):
        raise ValueError("Service point probabilities must be in [0.01, 0.99]")
    return deepcopy(_simulate_cached((p1, p2), best_of, deciding_tiebreak, rules))


def _winner_only(points, best_of, deciding_tiebreak, rules=STANDARD):
    need = best_of // 2 + 1
    ordinary = {}
    deciding = {}
    for server in (0, 1):
        for target, aggregate in ((7, ordinary), (deciding_tiebreak, deciding)):
            outcomes = defaultdict(float)
            for (a, b), prob in _set(points, server, target, rules, aggregate is deciding)[0].items():
                outcomes[int(b > a), server ^ ((a + b) % 2)] += prob
            aggregate[server] = outcomes

    @lru_cache(maxsize=None)
    def win(a, b, server):
        if max(a, b) == need:
            return float(a == need)
        edges = deciding if a == b == need - 1 else ordinary
        return sum(prob * win(a + (winner == 0), b + (winner == 1), next_server)
                   for (winner, next_server), prob in edges[server].items())

    return .5 * (win(0, 0, 0) + win(0, 0, 1))


@lru_cache(maxsize=4096)
def elo_shift(baseline, favorite_probability, best_of, deciding_tiebreak):
    """Invert the match chain along symmetric service shifts around the prior."""
    if favorite_probability == .5:
        return 0.
    low, high = 0., min(baseline - .05, .95 - baseline)
    for _ in range(15):
        shift = (low + high) / 2
        if _winner_only((baseline + shift, baseline - shift), best_of, deciding_tiebreak) < favorite_probability:
            low = shift
        else:
            high = shift
    return (low + high) / 2
