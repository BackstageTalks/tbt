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
    return {'brier': float(np.mean((p-y)**2)),
            'log_loss': float(log_loss(y, p, labels=[0, 1])),
            'confidence_gap': float(abs(np.mean(np.maximum(p, 1-p)) - np.mean((p >= .5) == y)))}


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
        # Symmetric positive-slope map preserves player orientation and winner.
        x, y = np.r_[parent[fit], 1-parent[fit]], np.r_[labels[fit], 1-labels[fit]]
        model = LogisticRegression(C=1., fit_intercept=False, max_iter=1000).fit(logits(x), y)
        if not np.isfinite(model.coef_).all() or model.coef_[0, 0] <= 0:
            audit['status'] = 'NONMONOTONE_REJECTED'
            continue
        fitted = ContextMap(model, len(fit)/(len(fit)+500.))
        baseline, target = parent[check], labels[check]
        alternative = fitted.predict(baseline)
        old, new = scores(baseline, target), scores(alternative, target)
        accepted = (new['log_loss'] + .001 < old['log_loss']
                    and new['brier'] <= old['brier'] + 1e-12
                    and new['confidence_gap'] <= old['confidence_gap'] + 1e-12)
        # Validate the actual existing publication transform, not just a hidden
        # intermediate probability. Do not change old model serving semantics.
        public_old = .5 + (baseline-.5)*depth[check]
        public_new = .5 + (alternative-.5)*depth[check]
        old_public, new_public = scores(public_old, target), scores(public_new, target)
        accepted = accepted and all(new_public[m] <= old_public[m] + 1e-12
                                    for m in ('brier', 'log_loss', 'confidence_gap'))
        baseline, alternative = public_old, public_new
        bands = {}
        for threshold in (.60, .70, .80):
            # Union prevents an override hiding its mistakes below a threshold.
            anchor = np.maximum(np.maximum(baseline, 1-baseline),
                                np.maximum(alternative, 1-alternative)) >= threshold
            n = int(anchor.sum())
            if n < 100:
                # Sparse evidence may reduce unsupported confidence, never boost it.
                safe = bool(np.all(np.maximum(alternative[anchor], 1-alternative[anchor])
                                   <= np.maximum(baseline[anchor], 1-baseline[anchor]) + 1e-12))
                bands[str(threshold)] = {'n': n, 'status': 'INSUFFICIENT_EVIDENCE', 'no_boost': safe}
            else:
                a, b = scores(baseline[anchor], target[anchor]), scores(alternative[anchor], target[anchor])
                safe = all(b[m] <= a[m] + 1e-12 for m in ('brier', 'log_loss', 'confidence_gap'))
                bands[str(threshold)] = {'n': n, 'baseline': a, 'candidate': b, 'accepted': safe}
            accepted = accepted and safe
        audit.update(status='SELECTED' if accepted else 'PARENT_RETAINED',
                     baseline=old, candidate=new, public_baseline=old_public,
                     public_candidate=new_public, validation_bands=bands, shrink_weight=fitted.weight)
        if accepted:
            selected[key] = fitted
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
