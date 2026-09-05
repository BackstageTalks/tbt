"""Descriptive coverage and out-of-time subgroup diagnostics, never confidence boosts."""
import pandas as pd
from ..models.metrics import evaluate_probabilities, wilson_interval


def history_band(count):
    return '0–9' if count < 10 else '10–29' if count < 30 else '30+'


def coverage(builder, match):
    states = [builder._state(match, side) for side in (True, False)]
    players = [{'matches': s.matches, 'surface_matches': s.surface_matches.get(match.surface, 0)} for s in states]
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
