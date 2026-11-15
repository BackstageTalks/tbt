"""Read-only sports probability audit; no fitting, price optimization or promotion.

One earliest snapshot >=06:00 per day; exact canonical identities. Compare fixed
top-3/5/7 and all >=65% candidates. Missing outcomes never cause replacements.
These are retrospective diagnostics, not certified publication thresholds.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from scripts.replay_selection_reliability import (
    anchors, load_snapshots, canonical_index, prepare, dt, metrics, sha,
)
from tbt.models.metrics import wilson_interval


def analyze(snapshots, matches):
    index = canonical_index(matches)
    daily = anchors(snapshots)
    diagnostics = Counter()
    groups = defaultdict(list)
    by_model = defaultdict(lambda: defaultdict(list))
    rows = []
    for day, snap in sorted(daily.items()):
        seen = set()
        for source in snap['rows']:
            try:
                if dt(source.get('created_at')) > dt(snap['generated_at']):
                    raise ValueError('future prediction')
            except ValueError:
                diagnostics['missing_or_future_prediction_time'] += 1
                continue
            row = prepare(source, dt(snap['generated_at']), day, index, diagnostics)
            if row is None:
                continue
            # An outcome may never choose which duplicate prediction to keep.
            key = row['event']
            if key in seen:
                diagnostics['duplicate_event_in_anchor'] += 1
                continue
            seen.add(key)
            label = str(source.get('tournament') or '') + ' ' + str(source.get('competition') or '')
            grade = re.search(r'\b([WM](?:15|25|35|50|60|75|80|100))\b', label.upper())
            row['cohort'] = grade.group(1) if grade else str(source.get('competition') or 'unknown')
            ev = source.get('feature_evidence') or {}
            row['statistics_state'] = ('paired_overall_and_surface'
                if ev.get('serve_return_known_both') is True and ev.get('surface_serve_return_known_both') is True
                else 'incomplete' if ev else 'not_recorded')
            rows.append(row)
            groups[row['cohort']].append(row)
            by_model[row['model']][day].append(row)
    def scored_metrics(items, field):
        result = metrics(items, field)
        settled = [r for r in items if type(r.get('correct')) is bool]
        result['hit_rate_ci95_wilson'] = (wilson_interval(sum(r['correct'] for r in settled), len(settled))
                                           if settled else None)
        return result
    def summary(items):
        return {'raw': scored_metrics(items, 'raw'), 'depth_adjusted': scored_metrics(items, 'public'),
                'historically_assigned_top_candidates': scored_metrics(
                    [r for r in items if r['section'] == 'top_daily'], 'public'),
                'mean_raw_probability': sum(r['raw'] for r in items)/len(items) if items else None,
                'statistics': dict(Counter(r['statistics_state'] for r in items))}
    models = {}
    for model, days in by_model.items():
        comparison = {}
        for field in ('raw', 'public'):
            for k in (3, 5, 7, None):
                selected, counts, positions = [], [], defaultdict(list)
                for day_rows in days.values():
                    ordered = sorted((r for r in day_rows if r[field] >= .65),
                                     key=lambda r: (-r[field], r['event']))
                    chosen = ordered if k is None else ordered[:k]
                    counts.append(len(chosen))
                    selected.extend(chosen)
                    for pos, row in enumerate(chosen, 1):
                        positions[pos].append(row)
                comparison[f'{field}_top_{k or "all"}'] = {
                    **scored_metrics(selected, field), 'days_observed_for_model': len(days),
                    'days_with_at_least_3': sum(n >= 3 for n in counts),
                    'fraction_days_with_at_least_3': sum(n >= 3 for n in counts)/len(days),
                    'positions': {str(p): scored_metrics(rs, field) for p, rs in positions.items()},
                }
        models[model] = comparison
    return {
        'status': 'RETROSPECTIVE_DIAGNOSTIC_NOT_PROMOTION_EVIDENCE',
        'snapshot_days': len(daily), 'first_day': min(daily, default=None),
        'last_day': max(daily, default=None), 'eligible_candidates': len(rows),
        'diagnostics': dict(diagnostics), 'cohorts': {k: summary(v) for k,v in groups.items()},
        'models': models,
        'limitations': [
            '65% is a fixed diagnostic floor, not a validated quality guarantee.',
            'Only days with available anchored snapshots are measured; missing days are not successes.',
            'Old snapshots without feature evidence cannot establish pre-match statistics coverage.',
            'No missing result is replaced by a lower-ranked settled candidate.',
            'No price, value or outcome influences sports ranking.',
            'Current canonical results join exact identities; stored counts do not prove calibration.',
            'selected_section means candidate assignment, NOT proof of public issuance.',
            'Pure sports comparisons include all recorded competitions; they are not the production TOP policy.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', nargs='+', type=Path, required=True)
    parser.add_argument('--canonical', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import pandas as pd
    columns = ['match_id','player1_id','player2_id','winner_id','status','scheduled_at',
               'tour','tournament_level','provider_context_json']
    report = analyze(load_snapshots(args.snapshots),
                     pd.read_parquet(args.canonical, columns=columns).to_dict('records'))
    report['input_sha256'] = {str(p): sha(p) for p in [*args.snapshots, args.canonical]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status','snapshot_days','eligible_candidates','cohorts')}))


if __name__ == '__main__':
    main()
