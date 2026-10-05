"""Zero-provider-call raw recovery triage and descriptive champion/market audit.

Never edits history, model, publication rules, or membership limits. Historical
open/close labels are source semantics, not independently verified tick times.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gc
import json
from pathlib import Path
import numpy as np
import pandas as pd
from _bootstrap import ROOT
from audit_environment_release import download_committed_history
from audit_high_impact import metrics, fitted_model_boundary
from release_store import ReleaseStore
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_market_history import clean_market_history_marker
from tbt.models.feature_builder import FeatureBuilder
from tbt.providers.statistics import complete_opponent_service_rates
from tbt.services.data_quality import audit_history


def quality_category(stats):
    pairs = [FeatureBuilder._extract_quality(stats, side) for side in ('p1', 'p2')]
    serve = all(v[0] is not None for v in pairs)
    ret = all(v[1] is not None for v in pairs)
    if serve and ret:
        return 'both_ready'
    if serve:
        return 'serve_only'
    if ret:
        return 'return_only'
    if any(v is not None for v in stats.values()):
        return 'partial_other_statistics'
    return 'no_statistics'


def recovery_inventory(matches):
    overall = Counter()
    segments = defaultdict(Counter)
    fields = Counter()
    transitions = Counter()
    for m in matches:
        stats = m.stats or {}
        before = quality_category(stats)
        repaired = dict(stats)
        complete_opponent_service_rates(repaired)
        after = quality_category(repaired)
        gained = sum(k not in stats or stats[k] is None for k in repaired if repaired[k] is not None)
        counters = [overall, segments['tour:' + m.tour.lower()], segments['year:' + str(m.scheduled_at.year)]]
        for c in counters:
            c['rows'] += 1
            c[before] += 1
            c['locally_recoverable_rows'] += int(bool(gained))
            c['locally_added_values'] += gained
            c['new_both_ready'] += int(before != 'both_ready' and after == 'both_ready')
        transitions[before + '->' + after] += 1
        fields.update(k for k, v in stats.items() if v is not None)
    return {'overall': dict(overall), 'segments': {k: dict(v) for k,v in segments.items()},
            'transitions': dict(transitions), 'observed_stat_fields': dict(fields),
            'policy': 'Exact opponent complement of an observed whole-match point rate only; no fabricated counts, rates, or API requests. Recovery simulation, canonical history untouched.'}


def align_market(market, swapped):
    """Historical marker uses original canonical player order, even after swap."""
    o1 = float(market['player1_odds'])
    o2 = float(market['player2_odds'])
    if swapped:
        o1, o2 = o2, o1
    p = (1/o1) / (1/o1 + 1/o2)
    return o1, o2, p


def comparison(rows):
    n = len(rows)
    if not n:
        return {'n': 0}
    p = np.array([r['model'] for r in rows])
    q = np.array([r['market'] for r in rows])
    y = np.array([r['target'] for r in rows])
    odds = np.array([[r['odds1'], r['odds2']] for r in rows])
    chosen = np.where(p >= .5, odds[:, 0], odds[:, 1])
    market_chosen = np.where(q >= .5, odds[:, 0], odds[:, 1])
    profits = np.where((p >= .5) == y, chosen - 1, -1)
    market_profits = np.where((q >= .5) == y, market_chosen - 1, -1)
    model = metrics(p, y)
    market = metrics(q, y)
    delta_loss = -(y*np.log(p)+(1-y)*np.log(1-p)) + (y*np.log(q)+(1-y)*np.log(1-q))
    return {'n': n, 'small_sample': n < 100, 'model': model, 'market': market,
            'model_minus_market_brier': model['brier']-market['brier'],
            'model_minus_market_log_loss': model['log_loss']-market['log_loss'],
            'paired_log_loss_delta_ci95_approx': [float(delta_loss.mean() - 1.96*delta_loss.std(ddof=1)/np.sqrt(n)), float(delta_loss.mean() + 1.96*delta_loss.std(ddof=1)/np.sqrt(n))] if n > 1 else None,
            'model_all_matches_flat_yield': float(profits.mean()),
            'market_favorites_flat_yield': float(market_profits.mean()),
            'staking_note': 'Every eligible matched event, flat 1u. Not actual published bets, no selector changes; correlated events and retrospective source labels limit inference.'}


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {k: comparison(v) for k,v in sorted(groups.items())}


def main():
    from tbt.models.artifact import load_model
    from tbt.services.training import _enforce_rank_provenance
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-repository', default='BackstageTalks/tbt-data')
    ap.add_argument('--out', default='.cache/tbt/existing-data-value/report.json')
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    directory = out.parent/'history'
    download_committed_history(ReleaseStore(args.data_repository, 'tbt-data-v1', directory), directory)
    raw = load_partitions(directory)
    safe, identity = sanitize_history_identities(raw)
    accepted, quality = audit_history(safe)
    report = {'schema': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
              'provider_requests': 0, 'production_mutated': False, 'phase': 'raw_inventory',
              'identity': identity, 'canonical_quality': quality,
              'local_recovery': recovery_inventory(accepted),
              'history_manifest': json.loads((directory/'history_manifest.json').read_text())}
    accepted_ids = {m.match_id for m in accepted}
    report['excluded_safe_rows'] = [{'match_id': m.match_id, 'completed': m.is_completed,
                                    'scheduled_at': m.scheduled_at.isoformat(),
                                    'statistics_fields': len(m.stats or {})}
                                   for m in safe if m.match_id not in accepted_ids]
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=str))
    print(json.dumps({'phase':'raw_inventory','local_recovery':report['local_recovery']['overall']}), flush=True)
    cleaned, ranks = _enforce_rank_provenance(accepted)
    del raw, safe, accepted, accepted_ids
    gc.collect()
    model_dir = out.parent/'model'
    ReleaseStore(args.data_repository,'tbt-model-production-v1',model_dir).download(
        extra_names=('model.joblib','training_report.json'),required_names=('model.joblib','training_report.json'))
    model = load_model(str(model_dir/'model.joblib'))
    cutoff = fitted_model_boundary(model.metadata)
    start = cutoff.normalize().to_pydatetime() + timedelta(days=1)
    recent = [m for m in cleaned if m.scheduled_at >= start]
    metadata = {}
    raw_market_count = 0
    for m in recent:
        market = clean_market_history_marker((m.provider_payload or {}).get('_tbt_market_history'))
        if market is not None:
            raw_market_count += 1
            oriented, _ = FeatureBuilder.orient_for_training(m)
            ranks_pair = (oriented.player1_rank, oriented.player2_rank)
            gap = abs(ranks_pair[0]-ranks_pair[1]) if all(v is not None for v in ranks_pair) else None
            metadata[m.match_id] = {'market': market, 'swapped': oriented.player1_id != m.player1_id,
                'level': m.tournament_level or 'unknown',
                'rank_gap': 'unknown' if gap is None else '0_20' if gap <= 20 else '21_100' if gap <=100 else '100_plus'}
    builder = FeatureBuilder()
    builder.replay(cleaned, before=start)
    del cleaned
    gc.collect()
    frame = builder.build_training_frame(recent)
    del builder, recent
    gc.collect()
    matched = frame.loc[frame.match_id.isin(metadata)].copy()
    report['model'] = {'version':model.version,'history_end':model.metadata.get('history_end'),
                       'post_fitting_boundary':str(cutoff),'rank_provenance':ranks}
    report['post_fitting_all_events'] = metrics(model.predict_proba(frame), frame.target) if len(frame) else {'n':0}
    report['post_fitting_by_tour'] = {str(k):metrics(model.predict_proba(g),g.target) for k,g in frame.groupby('tour')}
    report['matched_post_training_rows'] = raw_market_count
    report['comparison_policy'] = 'Identical whole-UTC-day events after all recorded fitting/calibration/evaluation boundaries and model availability. Descriptive, not an untouched promotion gate. Source opening/closing labels lack independently verified tick timestamps: not a measured publication CLV.'
    rows = {'opening': [], 'closing': []}
    if len(matched):
        matched['audit_p'] = model.predict_proba(matched)
        for row in matched.to_dict('records'):
            meta = metadata[row['match_id']]
            p = float(np.clip(row['audit_p'], 1e-9, 1-1e-9))
            for kind in rows:
                market = meta['market'].get(kind)
                if not market:
                    continue
                o1,o2,q = align_market(market, meta['swapped'])
                selected_q = q if p >= .5 else 1-q
                selected_odds = o1 if p >= .5 else o2
                gap = max(p,1-p)-selected_q
                rows[kind].append({'model':p,'market':q,'target':int(row['target']),
                    'odds1':o1,'odds2':o2,'tour':row['tour'],'surface':row['surface'],
                    'level':meta['level'],'rank_gap':meta['rank_gap'],
                    'favorite': 'favorite' if selected_q >= .5 else 'underdog',
                    'odds_band': 'below_1.5' if selected_odds <1.5 else '1.5_2' if selected_odds <2 else '2_3' if selected_odds <3 else '3_plus',
                    'disagreement':'negative' if gap <0 else '0_5pp' if gap <.05 else '5_15pp' if gap <.15 else '15pp_plus',
                    'depth':'below_075' if row['data_depth'] <.75 else '075_090' if row['data_depth'] <.9 else '090_plus'})
    report['market_comparison'] = {kind:{'overall':comparison(values),
        'segments':{key:grouped(values,key) for key in ('tour','surface','level','rank_gap','favorite','odds_band','disagreement','depth')}} for kind,values in rows.items()}
    report['phase'] = 'complete'
    out.write_text(json.dumps(report, indent=2, allow_nan=False, default=str))
    print(json.dumps({'phase':'complete','post_training_rows':len(frame),'matched_market_rows':len(matched)}),flush=True)


if __name__ == '__main__':
    main()
