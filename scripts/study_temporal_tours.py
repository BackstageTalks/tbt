"""Protected 2024+ temporal ATP/WTA research. Never exports a serving model."""
from __future__ import annotations
import gc
import json
from pathlib import Path
import numpy as np
import pandas as pd
from _bootstrap import ROOT
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import EVIDENCE_FEATURE_NAMES
from tbt.services.training import PRODUCTION_FEATURE_NAMES

ARMS = ('baseline', 'global_calibration', 'evidence', 'specialist', 'partial_pool')

STARTS = ('2025-01-01', '2025-04-01', '2025-07-01', '2025-10-01',
          '2026-01-01', '2026-04-01', '2026-07-01')


def partitions(frame, start):
    dates = pd.to_datetime(frame.scheduled_at, utc=True, errors='raise')
    if dates.isna().any() or frame.match_id.isna().any() or frame.match_id.duplicated().any():
        raise ValueError('Invalid dates or duplicate identities')
    if not frame.target.isin([0, 1]).all() or not frame.tour_atp.isin([0, 1]).all():
        raise ValueError('Invalid labels or tours')
    start = pd.Timestamp(start, tz='UTC')
    cal_start, select_start = start-pd.Timedelta(days=90), start-pd.Timedelta(days=30)
    end = start + pd.DateOffset(months=3)
    boundaries = (pd.Timestamp('2024-01-01', tz='UTC'), cal_start, select_start, start, end)
    return [frame.loc[(dates >= a) & (dates < b)].sort_values(['scheduled_at', 'match_id']).copy()
            for a, b in zip(boundaries, boundaries[1:])]


def metrics(y, p):
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    if not len(y) or len(y) != len(p) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('Invalid prediction vector')
    p = np.clip(p, 1e-9, 1-1e-9)
    return {'n': len(y), 'accuracy': float(np.mean((p >= .5) == y)),
            'log_loss': float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),
            'brier': float(np.mean((p-y)**2))}


def choose_weight(y, pooled, specialist):
    """Selection period only; accuracy first with proper-score safeguards."""
    base = metrics(y, pooled)
    eligible = [(0., base)]
    for weight in (.25, .5, .75, 1.):
        score = metrics(y, (1-weight)*pooled + weight*specialist)
        if score['log_loss'] <= base['log_loss'] and score['brier'] <= base['brier']:
            eligible.append((weight, score))
    return min(eligible, key=lambda x: (-x[1]['accuracy'], x[1]['log_loss'], x[0]))[0]


def summarize(rows):
    result = {}
    for name, group in [('all', rows), ('atp', rows[rows.tour_atp == 1]), ('wta', rows[rows.tour_atp == 0])]:
        if not len(group):
            continue
        scores = {arm: metrics(group.target, group[arm]) for arm in ARMS}
        # Paired daily-block bootstrap of accuracy differences. Not a promotion gate.
        base_correct = (group.baseline.to_numpy() >= .5) == group.target.to_numpy()
        for arm in ('global_calibration', 'evidence', 'specialist', 'partial_pool'):
            delta = ((group[arm].to_numpy() >= .5) == group.target.to_numpy()).astype(float) - base_correct
            days = pd.DataFrame({'day': pd.to_datetime(group.scheduled_at, utc=True).dt.normalize().to_numpy(), 'delta': delta}).groupby('day').delta.agg(['sum', 'count'])
            rng = np.random.default_rng(721)
            samples = rng.integers(0, len(days), size=(1000, len(days)))
            draws = days['sum'].to_numpy()[samples].sum(axis=1)/days['count'].to_numpy()[samples].sum(axis=1)
            scores[arm]['accuracy_delta'] = float(delta.mean())
            scores[arm]['daily_block_ci95'] = np.quantile(draws, [.025, .975]).tolist()
        result[name] = scores
    return result


def diagnostics(rows):
    """Descriptive segments and accuracy/coverage; never used to choose a model."""
    groups = {}
    for column in ('surface', 'competition', 'data_support'):
        if column not in rows:
            continue
        groups[column] = {
            str(key): {'n': len(part), 'small_sample': len(part) < 200,
                       'arms': {arm: metrics(part.target, part[arm]) for arm in ARMS}}
            for key, part in rows.groupby(column, dropna=False)
        }
    confidence = {}
    for tour, part in [('all', rows), ('atp', rows[rows.tour_atp == 1]), ('wta', rows[rows.tour_atp == 0])]:
        if not len(part):
            continue
        confidence[tour] = {}
        for arm in ARMS:
            selected = part.loc[np.maximum(part[arm], 1-part[arm]) >= .8]
            confidence[tour][arm] = {'n': len(selected), 'coverage': len(selected)/len(part),
                                    'accuracy': metrics(selected.target, selected[arm])['accuracy'] if len(selected) else None}
    return {'segments': groups, 'confidence_at_least_80': confidence,
            'confidence_policy': 'Each arm selects its own subset; compare coverage alongside accuracy. Not paired evidence of improved winner selection.'}


def study(frame, output, factory=TennisEnsemble, starts=STARTS):
    names = list(PRODUCTION_FEATURE_NAMES) + list(EVIDENCE_FEATURE_NAMES)
    report = {'status': 'EXECUTING', 'production_mutated': False, 'automatic_activation': False,
              'training_start': '2024-01-01', 'primary_metric': 'paired_winner_accuracy',
              'protocol': 'expanding train; 60d calibration; 30d model selection; next calendar quarter test',
              'features': names, 'folds': [], 'limitations': [
                  'Retrospective development evidence, not an untouched promotion holdout.',
                  'Shared base features only; external ranking/season enrichments are excluded in all arms.',
                  'Daily block intervals do not fully capture player/tournament dependence or multiple comparisons.',
                  'No production model or candidate artifact is published.']}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary = output.with_suffix('.json.part')
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False, default=str), encoding='utf-8')
        temporary.replace(output)
    save()
    collected = []
    for start in starts:
        train, cal, select, test = partitions(frame, start)
        if min(map(len, (train, cal, select, test))) < 300:
            report['folds'].append({'start': start, 'status': 'INSUFFICIENT_DATA', 'counts': list(map(len, (train, cal, select, test)))})
            save()
            continue
        fold = {'start': start, 'status': 'EVALUATED', 'partitions': {
            key: {'n': len(part), 'first': str(part.scheduled_at.min()), 'last': str(part.scheduled_at.max())}
            for key, part in zip(('train', 'calibration', 'selection', 'test'), (train, cal, select, test))}, 'tour_choices': {}}
        columns = ['match_id', 'scheduled_at', 'target', 'tour_atp']
        columns += [name for name in ('surface', 'competition', 'data_support') if name in test]
        row = test[columns].copy()
        selection = {}
        fold['calibration_choices'] = {}
        for arm, features in [('baseline', PRODUCTION_FEATURE_NAMES), ('evidence', names)]:
            model = factory(feature_names=list(features), objective='log_loss')
            model.fit(train, cal)
            row[arm] = model.predict_proba(test)
            fold['calibration_choices'][arm] = dict(getattr(model, 'metadata', {}))
            if arm == 'baseline':
                row['global_calibration'] = model._calibrated(model.calibrator, model._raw(test))
            selection[arm] = model.predict_proba(select)
            del model
            gc.collect()
        row['specialist'] = row.evidence
        row['partial_pool'] = row.evidence
        for tour, value in [('atp', 1), ('wta', 0)]:
            tr, ca, se, te = [part.loc[part.tour_atp == value] for part in (train, cal, select, test)]
            if len(tr) < 1000 or len(ca) < 300 or len(se) < 200 or len(te) < 100 or tr.target.nunique() < 2:
                fold['tour_choices'][tour] = {'status': 'POOLED_FALLBACK', 'counts': list(map(len, (tr, ca, se, te)))}
                continue
            model = factory(feature_names=names, objective='log_loss')
            model.fit(tr, ca)
            select_mask = select.tour_atp.to_numpy() == value
            weight = choose_weight(se.target, selection['evidence'][select_mask], model.predict_proba(se))
            prediction = model.predict_proba(te)
            row.loc[te.index, 'specialist'] = prediction
            row.loc[te.index, 'partial_pool'] = (1-weight)*row.loc[te.index, 'evidence'] + weight*prediction
            fold['tour_choices'][tour] = {'status': 'EVALUATED', 'specialist_weight': weight}
            del model
            gc.collect()
        fold['results'] = summarize(row)
        fold['diagnostics'] = diagnostics(row)
        import hashlib
        fingerprint = pd.util.hash_pandas_object(row, index=False).values.tobytes()
        fold['prediction_checkpoint'] = {'sha256': hashlib.sha256(fingerprint).hexdigest(), 'rows': len(row)}
        report['folds'].append(fold)
        collected.append(row)
        save()
        print(json.dumps({'fold': start, 'status': 'EVALUATED', 'results': fold['results']}), flush=True)
    if not collected:
        raise ValueError('No eligible temporal folds')
    joined = pd.concat(collected, ignore_index=True)
    if joined.match_id.duplicated().any():
        raise ValueError('Overlapping test folds')
    report['overall'] = summarize(joined)
    report['diagnostics'] = diagnostics(joined)
    report['status'] = 'COMPLETED_RESEARCH_ONLY'
    report['evaluated_folds'] = len(collected)
    save()
    return report


def main():
    from guarded_candidate_backup import BASE, validate_certificate
    from tbt.data.history_snapshot import load_partitions
    from tbt.data.history_safety import sanitize_history_identities
    from verified_training_frame import load
    cert = validate_certificate(require_writer_lock=False)
    audit = json.loads((BASE/'production/leakage_audit_report.json').read_text())
    if audit.get('status') != 'pass':
        raise RuntimeError('Passing leakage audit required')
    matches, _ = sanitize_history_identities(load_partitions(BASE/'history'))
    frame = load(BASE/'verified-training-features.parquet', 'top-7.2.1', matches)
    levels = {str(m.match_id): m.tournament_level or 'unknown' for m in matches}
    frame['competition'] = frame.match_id.astype(str).map(levels).fillna('unknown')
    # Fixed reporting categories, not learned thresholds or selection rules.
    support = frame[['serve_evidence_depth', 'return_evidence_depth']].min(axis=1)
    frame['data_support'] = pd.cut(support, [-1, 0, .25, 1], labels=['missing', 'sparse', 'observed'])
    del matches, levels
    report_path = BASE/'training-backup/temporal-tour-study.json'
    study(frame, report_path)
    validate_certificate(require_writer_lock=False)
    report = json.loads(report_path.read_text())
    report['verified_backup'] = {key: cert[key] for key in ('run_id', 'application_sha', 'remote_manifest_sha256')}
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
