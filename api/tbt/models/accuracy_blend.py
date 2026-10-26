"""7.2.2 candidate-only accuracy search on chronological calibration slices."""
import numpy as np
from sklearn.metrics import log_loss


def select_accuracy_blend(linear, boost, elo, labels, tours, split, baseline):
    arrays = [np.asarray(v, dtype=float) for v in (linear, boost, elo, labels, tours)]
    linear, boost, elo, labels, tours = arrays
    if (any(v.ndim != 1 or len(v) != len(labels) or not np.isfinite(v).all() for v in arrays)
            or not 0 < split < len(labels) or not np.isin(labels, [0, 1]).all()
            or not np.isin(tours, [0, 1]).all()
            or any(((v < 0) | (v > 1)).any() for v in arrays[:3])):
        raise ValueError("Invalid accuracy blend inputs")

    def predict(weights):
        b, e = weights
        return np.clip((1-e)*(b*boost+(1-b)*linear)+e*elo, .01, .99)

    def metrics(p, mask):
        y, p = labels[mask], p[mask]
        return {"n": int(len(y)), "accuracy": float(np.mean((p >= .5) == y)),
                "log_loss": float(log_loss(y, p, labels=[0, 1])),
                "brier": float(np.mean((p-y)**2))}

    fit = np.arange(len(labels)) < split
    validation = ~fit
    evidence = {"status": "INSUFFICIENT_DATA", "holdout_used": False,
                "minimum_accuracy_gain": .002, "baseline_weights": list(baseline)}
    if fit.sum() < 500 or validation.sum() < 250:
        return None, evidence
    masks = {"all": validation, "atp": validation & (tours == 1),
             "wta": validation & (tours == 0)}
    if any(mask.sum() < 120 or len(np.unique(labels[mask])) < 2 for mask in masks.values()):
        return None, evidence
    base = predict(baseline)
    base_fit = metrics(base, fit)
    grid = [(float(b), e) for b in np.linspace(0., 1., 6) for e in (0., .25, .5, 1.)]
    grid_baseline = tuple(map(float, baseline))
    # Fit labels alone choose one challenger; later labels may only accept/reject it.
    grid.append(grid_baseline)
    eligible = []
    for weights in grid:
        score = metrics(predict(weights), fit)
        if score['log_loss'] <= base_fit['log_loss'] + 1e-12 and score['brier'] <= base_fit['brier'] + 1e-12:
            eligible.append((weights, score))
    chosen, _ = min(eligible, key=lambda item: (-item[1]['accuracy'], item[1]['log_loss'],
                                               item[0] != tuple(baseline)))
    candidate = predict(chosen)
    comparison = {name: {"baseline": metrics(base, mask), "candidate": metrics(candidate, mask)}
                  for name, mask in masks.items()}
    approved = all(item['candidate']['accuracy'] >= item['baseline']['accuracy']
                   and item['candidate']['log_loss'] <= item['baseline']['log_loss'] + 1e-12
                   and item['candidate']['brier'] <= item['baseline']['brier'] + 1e-12
                   for item in comparison.values())
    approved = approved and comparison['all']['candidate']['accuracy'] - comparison['all']['baseline']['accuracy'] >= .002
    evidence.update(status='ACCEPTED' if approved else 'BASELINE_RETAINED',
                    selected_on_early_slice=list(chosen), validation=comparison)
    return (chosen if approved else None), evidence
