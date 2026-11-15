"""Descriptive coverage and out-of-time subgroup diagnostics, never confidence boosts."""
import math
import pandas as pd
from ..models.metrics import evaluate_probabilities, wilson_interval
from ..models.feature_builder import stats_surface_key


def history_band(count):
    return '0–9' if count < 10 else '10–29' if count < 30 else '30+'


def coverage(builder, match):
    states = [builder._state(match, side) for side in (True, False)]
    surface_key = stats_surface_key(match.surface)
    players = [{'matches': s.matches, 'surface_matches': s.surface_matches.get(surface_key, 0)} for s in states]
    for player, state in zip(players, states):
        # This is the actual retained feature-state window, not lifetime coverage.
        past = [r for r in state.recent if r.played_at < match.scheduled_at]
        def valid(value):
            try:
                number = float(value)
                return math.isfinite(number) and 0 <= number <= 1
            except (TypeError, ValueError, OverflowError):
                return False
        def summarize(rows):
            paired = [r for r in rows if valid(r.serve_quality) and valid(r.return_quality)]
            weights = [0.5 ** ((match.scheduled_at-r.played_at).total_seconds()/86400/120)
                       for r in paired]
            return {
                'observed_matches': len(rows), 'paired_serve_return_matches': len(paired),
                'paired_coverage': len(paired)/len(rows) if rows else None,
                'paired_effective_sample': (sum(weights)**2/sum(w*w for w in weights)
                                           if weights and sum(w*w for w in weights) else 0.0),
                'latest_paired_age_days': min(
                    ((match.scheduled_at-r.played_at).total_seconds()/86400 for r in paired),
                    default=None),
            }
        player['statistics_evidence'] = {
            'scope': 'retained_prematch_feature_state_not_lifetime',
            'overall': summarize(past),
            'surface': summarize([r for r in past if surface_key != 'unknown'
                                  and stats_surface_key(r.surface) == surface_key]),
            'future_or_same_time_rows_excluded': len(state.recent)-len(past),
        }
    return {'player1': players[0], 'player2': players[1],
            'history_band': history_band(min(p['matches'] for p in players)),
            'surface_history_band': history_band(min(p['surface_matches'] for p in players)),
            'surface_known': match.surface != 'unknown',
            'meaning': 'observed_history_counts_not_probability_of_success'}


def subgroup_report(frame, probabilities):
    scored = frame.reset_index(drop=True).copy()
    scored['probability'] = list(probabilities)
    output = {}
    for column in ('tour', 'surface', 'competition', 'tournament', 'history_band', 'surface_history_band'):
        if column not in scored:
            continue
        groups = {}
        for value, group in scored.groupby(column, dropna=False):
            metrics = evaluate_probabilities(group.target, group.probability)
            n = metrics['n']
            groups[str(value)] = {k: metrics[k] for k in ('n', 'accuracy', 'log_loss', 'brier_score', 'ece_10')}
            groups[str(value)].update({'coverage': n / len(scored), 'small_sample': n < 100,
                'accuracy_ci95_wilson': wilson_interval(round(metrics['accuracy'] * n), n)})
        output[column] = groups
    return output
