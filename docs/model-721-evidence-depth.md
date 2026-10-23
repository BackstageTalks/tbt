# 7.2.1 recent evidence depth experiment

Adds six bounded, player-swap-invariant inputs to new top-7.2.1 fits only. Existing production feature lists and serialized artifacts retain their features.

Counts use the weaker-supported player, earlier UTC days only, a 365-day window, a 120-day half-life and saturation at 20 effective observations. Surface support pools hard/indoor hard and treats unknown surfaces as unavailable. Missing, nonfinite and out-of-range serve/return observations contribute no statistical support. These are model inputs, not calibrated confidence scores or betting filters.

Rationale: lifetime data_depth saturates at 50 career matches and cannot distinguish current statistical coverage from an old career. Existing form, surface, fatigue and workload inputs remain available.

Validation: point-in-time exclusion, missingness, surface pooling, weaker-player support, symmetry, candidate-only scope, existing feature/training/portable-model tests. Protected workflow performs input freezing, backup read-back, restore and leakage checks before fitting; dispatch with auto_shadow=false. No production promotion.

Evaluation caveat: the existing September/October holdout has already been examined. Another score on overlapping matches is a development comparison, not new independent confirmation. Do not replace the active candidate based only on that score. Require subsequent prospective results and inspect ATP/WTA and competition segments; a measured lift is not yet established. DIL imports are not automatically canonical training inputs and are not joined by uncertain identities in this change.
