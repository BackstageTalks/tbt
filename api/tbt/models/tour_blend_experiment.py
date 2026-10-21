"""Candidate-only raw blend experiment; never changes serving weights."""
import numpy as np
from sklearn.metrics import log_loss


def compare_tour_blends(linear, boost, elo, labels, tours, split, shared):
    arrays = [np.asarray(x, dtype=float) for x in (linear, boost, elo, labels, tours)]
    linear, boost, elo, labels, tours = arrays
    if (any(x.ndim != 1 or len(x) != len(labels) or not np.isfinite(x).all()
            for x in arrays) or not 0 < split < len(labels)
            or not np.isin(labels, [0, 1]).all()
            or not np.isin(tours, [0, 1]).all()
            or any(((x < 0) | (x > 1)).any() for x in arrays[:3])):
        raise ValueError("Invalid tour blend experiment inputs")

    def predict(weights):
        b, e = weights
        return np.clip((1-e) * (b*boost + (1-b)*linear) + e*elo, .01, .99)

    def metrics(p, mask):
        y, p = labels[mask], p[mask]
        return {"n": int(len(y)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
                "brier": float(np.mean((p-y)**2)),
                "accuracy": float(np.mean((p >= .5) == y))}

    def weights(w):
        b, e = map(float, w)
        return {"linear": (1-e)*(1-b), "boost": (1-e)*b, "elo": e}

    baseline = predict(shared)
    report = {"status": "EXPERIMENT_ONLY", "probability_basis": "uncalibrated",
              "holdout_used": False, "serving_weights_changed": False,
              "shared_weights": weights(shared), "tours": {}}
    for tour, value in (("atp", 1), ("wta", 0)):
        fit = (tours == value) & (np.arange(len(labels)) < split)
        validation = (tours == value) & (np.arange(len(labels)) >= split)
        if fit.sum() < 250 or validation.sum() < 120 or len(np.unique(labels[fit])) < 2:
            report["tours"][tour] = {"status": "INSUFFICIENT_DATA"}
            continue
        grid = [(float(b), e) for b in np.linspace(0, 1, 6) for e in (0., .25, .5, 1.)]
        # Same grid/objective as the probability model; validation labels
        # cannot affect selected weights. Prefer shared weights on exact ties.
        chosen = min(grid, key=lambda w: (metrics(predict(w), fit)["log_loss"],
                                         w != tuple(shared), w))
        candidate = predict(chosen)
        before, after = metrics(baseline, validation), metrics(candidate, validation)
        report["tours"][tour] = {
            "status": "EVALUATED", "fit_n": int(fit.sum()),
            "weights": weights(chosen), "shared": before, "specialized": after,
            "delta": {k: after[k]-before[k] for k in ("log_loss", "brier", "accuracy")},
        }
    return report
