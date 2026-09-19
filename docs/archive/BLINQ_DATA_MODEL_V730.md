# BlinQ Data Model v3 — v7.3.0

The first v3 release intentionally starts with features that are derivable from canonical point-in-time history and already verified SG/statistics enrichment. This adds predictive depth without consuming additional Tennis API calls.

New model features are surface-specific serve/return, surface H2H, set/game workload over 7 and 14 days, deciding-set record, lost-first-set second-set recovery, first-set closing record, round form and tournament history. Every sparse context has a separate known/coverage feature and is shrunk toward neutral.

`feature-audit` is a zero-Tennis-API workflow mode that downloads the canonical production history and writes `.cache/tbt/feature-v3/coverage.json`. `mega-data` also emits the same coverage report after enrichment.

PBP pressure features and multi-book odds consensus are deliberately not added to the trainable feature list yet. They require a verified provider endpoint/payload and historical point-in-time coverage first. This prevents silent leakage and distribution shifts.

After a large enrichment run, run `feature-audit`, then `train`, then `backtest`. Only promote a new model after chronological holdout/calibration checks pass.
