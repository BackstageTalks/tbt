"""One versioned native artifact containing already fitted tour components."""
from copy import deepcopy
import math

from .ensemble import TennisEnsemble
from .tour_pooling import pooled_predictions


class TourBundle(TennisEnsemble):
    def __init__(self, pooled, specialists, weights, *, version):
        # Do not construct or fit unused sklearn estimators.
        self.pooled = deepcopy(pooled)
        self.specialists = deepcopy(specialists)
        self.weights = dict(weights)
        self.version = version
        self.feature_names = list(pooled.feature_names)
        self.metadata = {"architecture": "tour_partial_pool_v1",
                         "specialist_weights": dict(weights),
                         "component_versions": {"pooled": pooled.version,
                             **{k: v.version for k, v in specialists.items()}}}
        self.fitted = True
        self.validate()

    def validate(self):
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("Bundle version required")
        if set(self.specialists) - {"atp", "wta"} or set(self.weights) - {"atp", "wta"}:
            raise ValueError("Unknown tour")
        for tour, weight in self.weights.items():
            if (isinstance(weight, bool) or not isinstance(weight, (int, float))
                    or not math.isfinite(weight) or not 0 <= weight <= 1):
                raise ValueError("Invalid specialist weight")
            if weight > 0 and tour not in self.specialists:
                raise ValueError("Missing specialist")
        for model in [self.pooled, *self.specialists.values()]:
            if (not isinstance(model, TennisEnsemble) or isinstance(model, TourBundle)
                    or not model.fitted or list(model.feature_names) != self.feature_names):
                raise ValueError("Incompatible or unfitted bundle component")

    def fit(self, *args, **kwargs):
        raise RuntimeError("Fit components only through the governed training workflow")

    def predict_proba(self, frame):
        self.validate()
        return pooled_predictions(frame, self.pooled, self.specialists, self.weights)
