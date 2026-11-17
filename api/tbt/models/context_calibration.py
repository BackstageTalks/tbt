"""Candidate-only sports-context calibration, validated on later whole days.

No odds, publication outcomes or holdout labels are inputs to fitting/selection.
Unknown competition encodings retain the parent map. Existing artifacts do not
activate this layer unless they contain explicitly accepted context maps.
"""
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss


def masks(frame):
    required = {'tour_atp', 'tournament_level'}
    if not required.issubset(frame.columns):
        raise ValueError('Sports context calibration requires original feature columns')
    tour = frame.tour_atp.to_numpy(dtype=float)
    level = frame.tournament_level.to_numpy(dtype=float)
    if not np.isin(tour, [0., 1.]).all() or not np.isfinite(level).all():
        raise ValueError('Invalid sports context calibration features')
    # FeatureBuilder._level_value: 0.35 is ambiguous (generic tours AND UTR).
    # Never infer main-tour membership from that fallback or the gender alone.
    groups = {'main': np.isin(level, [.45, .6, .8, 1.]),
              'challenger': level == .25, 'itf': level == .1}
    if 'competition' in frame.columns:
        # A generic ATP/WTA level is not sufficient when the actual tournament
        # says ITF, UTR, Challenger or WTA 125. Use original pre-match metadata;
        # this is the same precedence principle as the separate TOP gate.
        names = frame.competition.fillna('').astype(str).str.lower().str.strip()
        events = (frame.tournament.fillna('').astype(str).str.lower().str.strip()
                  if 'tournament' in frame.columns else names * 0)
        combined = names + ' ' + events
        itf = combined.str.contains(r'\bitf\b|\bfutures?\b', regex=True).to_numpy()
        utr = combined.str.contains(r'\butr\b', regex=True).to_numpy()
        challenger = combined.str.contains('challenger', regex=False).to_numpy() & ~itf & ~utr
        wta125 = combined.str.contains(r'\bwta\s*125\b', regex=True).to_numpy()
        other = combined.str.contains(
            r'\bdoubles?\b|\bwheelchair\b|\bjunior\b|\bexhibition\b',
            regex=True).to_numpy()
        main = names.isin({'atp', 'wta', 'atp 250', 'atp 500', 'atp 1000',
                           'wta 250', 'wta 500', 'wta 1000', 'masters 1000',
                           'atp finals', 'wta finals', 'grand slam', 'grand slams'}).to_numpy()
        # pandas may expose read-only NumPy views under copy-on-write.
        # Build a fresh mask instead of mutating the Series' backing array.
        main = main & ~(itf | utr | challenger | wta125 | other)
        # An incorrect gender/competition label is not calibration evidence.
        incompatible = ((tour == 1.) & names.str.startswith('wta').to_numpy()) | (
            (tour == 0.) & names.str.startswith('atp').to_numpy())
        main = main & ~incompatible
        groups = {'main': main, 'challenger': challenger & ~other,
                  'itf': itf & ~other}
    return {f'{name}_{sex}': group & (tour == value)
            for name, group in groups.items() for sex, value in [('atp', 1.), ('wta', 0.)]}


def logits(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1-1e-6)
    return np.log(p/(1-p)).reshape(-1, 1)


@dataclass
class ContextMap:
    model: object
    weight: float

    def predict(self, p):
        p = np.asarray(p, dtype=float)
        calibrated = self.model.predict_proba(logits(p))[:, 1]
        return np.clip((1-self.weight)*p + self.weight*calibrated, .01, .99)


def scores(p, y):
    """Proper scores and confidence reliability on exactly the same rows."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=int)
    confidence = np.maximum(p, 1-p)
    correct = ((p >= .5) == y).astype(float)
    # Ten equal-width confidence bins [0.50, 1.00]. A mean confidence
    # gap can cancel overconfidence in one bin with underconfidence in another.
    bucket = np.clip(np.floor((confidence-.5)*20).astype(int), 0, 9)
    ece = sum(float(np.sum(bucket == b)) / len(p) *
              abs(float(np.mean(confidence[bucket == b])) -
                  float(np.mean(correct[bucket == b])))
              for b in range(10) if np.any(bucket == b))
    return {'brier': float(np.mean((p-y)**2)),
            'log_loss': float(log_loss(y, p, labels=[0, 1])),
            'confidence_gap': float(abs(np.mean(confidence) - np.mean(correct))),
            'confidence_ece_10': float(ece)}


def choose(frame, parent, labels, split):
    """Fit earlier rows only; accept exact fitted map, never refit on selection."""
    parent, labels = np.asarray(parent, dtype=float), np.asarray(labels)
    if (parent.ndim != 1 or len(frame) != len(parent) or labels.shape != parent.shape
            or not 0 < split < len(parent) or not np.isfinite(parent).all()
            or not ((parent > 0) & (parent < 1)).all() or not np.isin(labels, [0, 1]).all()):
        raise ValueError('Invalid chronological context calibration inputs')
    import pandas as pd
    days = pd.to_datetime(frame.scheduled_at, utc=True).dt.normalize()
    if days.isna().any() or not days.is_monotonic_increasing or days.iloc[split-1] >= days.iloc[split]:
        raise ValueError('Context calibration requires disjoint whole chronological days')
    depth = frame.data_depth.to_numpy(dtype=float)
    if not np.isfinite(depth).all() or not ((depth >= 0) & (depth <= 1)).all():
        raise ValueError('Invalid publication depth evidence')
    selected, report = {}, {}
    for key, mask in masks(frame).items():
        fit = np.flatnonzero(mask[:split])
        check = np.flatnonzero(mask[split:]) + split
        audit = {'fit_n': len(fit), 'validation_n': len(check), 'refit_on_validation': False}
        report[key] = audit
        if len(fit) < 250 or len(check) < 120 or len(np.unique(labels[fit])) < 2:
            audit['status'] = 'INSUFFICIENT_EVIDENCE'
            continue
        # Fit only on earlier days; a later disjoint period may select between
        # two predefined shrinkages, never refit on selection or final holdout.
        x, y = np.r_[parent[fit], 1-parent[fit]], np.r_[labels[fit], 1-labels[fit]]
        model = LogisticRegression(C=1., fit_intercept=False, max_iter=1000).fit(logits(x), y)
        if not np.isfinite(model.coef_).all() or model.coef_[0, 0] <= 0:
            audit['status'] = 'NONMONOTONE_REJECTED'
            continue
        fitted_weight = len(fit)/(len(fit)+500.)
        baseline, target = parent[check], labels[check]
        depth_check = depth[check]
        public_old = .5 + (baseline-.5)*depth_check
        old, old_public = scores(baseline, target), scores(public_old, target)
        options = []
        for factor in (.5, 1.):
            fitted = ContextMap(model, fitted_weight * factor)
            alternative = fitted.predict(baseline)
            new = scores(alternative, target)
            public_new = .5 + (alternative-.5)*depth_check
            new_public = scores(public_new, target)
            # All proper scores, global reliability, and real displayed
            # confidence ECE must not regress on later calibration days.
            accepted = (new['log_loss'] + .001 < old['log_loss']
                        and all(new[m] <= old[m] + 1e-12
                                for m in ('brier', 'confidence_gap', 'confidence_ece_10'))
                        and all(new_public[m] <= old_public[m] + 1e-12
                                for m in ('brier', 'log_loss', 'confidence_gap',
                                          'confidence_ece_10')))
            bands = {}
            for threshold in (.60, .70, .80):
                # Union prevents a map from hiding mistakes below a threshold.
                anchor = np.maximum(np.maximum(public_old, 1-public_old),
                                    np.maximum(public_new, 1-public_new)) >= threshold
                n = int(anchor.sum())
                minimum = 250 if threshold >= .80 else 100
                if n < minimum:
                    # At 80%+ we need a larger independent cohort than the
                    # old 100-row gate before increasing published certainty.
                    # Unsupported confidence may shrink, but never be boosted.
                    safe = bool(np.all(np.maximum(public_new[anchor], 1-public_new[anchor])
                                       <= np.maximum(public_old[anchor], 1-public_old[anchor]) + 1e-12))
                    bands[str(threshold)] = {'n': n, 'minimum_rows': minimum,
                                             'status': 'INSUFFICIENT_EVIDENCE',
                                             'no_boost': safe}
                else:
                    base_band = scores(public_old[anchor], target[anchor])
                    new_band = scores(public_new[anchor], target[anchor])
                    safe = all(new_band[m] <= base_band[m] + 1e-12
                               for m in ('brier', 'log_loss', 'confidence_gap'))
                    # ECE is too unstable on very small subsets. Require
                    # non-regression only when a full calibration-bin audit
                    # has at least 250 independent outcomes.
                    if n >= 250:
                        safe = safe and (new_band['confidence_ece_10']
                                         <= base_band['confidence_ece_10'] + 1e-12)
                    bands[str(threshold)] = {
                        'n': n, 'baseline': base_band, 'candidate': new_band,
                        'accepted': bool(safe), 'ece_gate_applied': n >= 250}
                accepted = accepted and safe
            # Ranking tail and unknown ranking evidence must not inherit a
            # pooled high-confidence boost from mostly top-ranked fixtures.
            # Compare *published* probabilities in the same later calibration
            # rows, with no selection on final holdout or issued results.
            rank_checks = {}
            tour = key.rsplit('_', 1)[-1]
            known_column = f'{tour}_hist_known_both'
            worst_column = f'{tour}_hist_worst_rank_log'
            if known_column in frame.columns and worst_column in frame.columns:
                known = frame[known_column].iloc[check].to_numpy(dtype=float)
                worst = frame[worst_column].iloc[check].to_numpy(dtype=float)
                if (not np.isfinite(known).all() or not np.isin(known, [0., 1.]).all()
                        or not np.isfinite(worst).all()):
                    raise ValueError('Invalid weekly rank-tail calibration evidence')
                tail_cutoff = 2000 if tour == 'atp' else 1000
                rank_cohorts = {
                    'weekly_rank_missing': known == 0.,
                    'tail_rank': (known == 1.) & (worst >= np.log1p(tail_cutoff)),
                }
                for cohort, cohort_mask in rank_cohorts.items():
                    count = int(cohort_mask.sum())
                    if count == 0:
                        rank_checks[cohort] = {'n': 0, 'status': 'NO_EVIDENCE'}
                        continue
                    before_conf = np.maximum(public_old[cohort_mask], 1-public_old[cohort_mask])
                    after_conf = np.maximum(public_new[cohort_mask], 1-public_new[cohort_mask])
                    if count < 250:
                        safe = bool(np.all(after_conf <= before_conf + 1e-12))
                        rank_checks[cohort] = {
                            'n': count, 'minimum_rows': 250,
                            'status': 'INSUFFICIENT_EVIDENCE',
                            'no_boost': safe}
                    else:
                        base_rank = scores(public_old[cohort_mask], target[cohort_mask])
                        new_rank = scores(public_new[cohort_mask], target[cohort_mask])
                        safe = all(new_rank[m] <= base_rank[m] + 1e-12 for m in (
                            'brier', 'log_loss', 'confidence_gap', 'confidence_ece_10'))
                        rank_checks[cohort] = {
                            'n': count, 'status': 'EVALUATED',
                            'baseline': base_rank, 'candidate': new_rank,
                            'accepted': safe}
                    accepted = accepted and safe
            details = {'rank_tail_validation': rank_checks,
                       'baseline': old, 'candidate': new,
                       'public_baseline': old_public, 'public_candidate': new_public,
                       'validation_bands': bands, 'shrink_weight': fitted.weight,
                       'accepted': bool(accepted)}
            options.append((fitted, details))
        eligible = [(candidate, details) for candidate, details in options
                    if details['accepted']]
        # Optimize only on disjoint calibration days. Ties prefer less change.
        chosen, details = min(
            eligible if eligible else options,
            key=lambda entry: (entry[1]['public_candidate']['log_loss'],
                               entry[0].weight))
        audit.update({**details,
                      'status': 'SELECTED' if eligible else 'PARENT_RETAINED',
                      'validated_shrink_options': [
                          {'weight': candidate.weight,
                           'accepted': check_result['accepted'],
                           'public_log_loss': check_result['public_candidate']['log_loss'],
                           'public_ece_10': check_result['public_candidate']['confidence_ece_10']}
                          for candidate, check_result in options],
                      'choice_never_uses_final_holdout': True})
        if eligible:
            selected[key] = chosen
    return selected, report


def apply(frame, parent, maps):
    p = np.asarray(parent, dtype=float).copy()
    if maps:
        groups = masks(frame)
        if set(maps)-set(groups):
            raise ValueError('Unknown context map')
        for key, mapping in maps.items():
            mask = groups[key]
            if mask.any():
                p[mask] = mapping.predict(p[mask])
    return p


def holdout_report(frame, parent, candidate):
    """Read-only ablation on the same rows; never controls map selection."""
    parent, candidate = np.asarray(parent), np.asarray(candidate)
    y = frame.target.to_numpy(dtype=int)
    depth = frame.data_depth.to_numpy(dtype=float)
    groups = {'all': np.ones(len(frame), dtype=bool), **masks(frame)}
    result = {}
    for key, mask in groups.items():
        if not mask.any():
            continue
        a, b, target = parent[mask], candidate[mask], y[mask]
        pa, pb = .5+(a-.5)*depth[mask], .5+(b-.5)*depth[mask]
        bands = {}
        for threshold in (.60, .70, .80):
            anchor = np.maximum(pa, 1-pa) >= threshold
            if anchor.any():
                bands[str(threshold)] = {'n': int(anchor.sum()),
                    'parent': scores(pa[anchor], target[anchor]),
                    'candidate': scores(pb[anchor], target[anchor])}
        result[key] = {'n': int(mask.sum()), 'parent': scores(a, target),
                       'candidate': scores(b, target), 'public_parent': scores(pa, target),
                       'public_candidate': scores(pb, target), 'parent_anchored_bands': bands}
    return {'status': 'READ_ONLY_SAME_HOLDOUT_ABLATION_NOT_PROSPECTIVE_TOP',
            'odds_used': False, 'holdout_used_for_fitting': False, 'groups': result}
