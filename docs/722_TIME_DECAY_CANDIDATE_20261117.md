# 7.2.2 candidate-only time-decay experiment (2026-11-17)

## Status and authority
PREPARED implementation; not a demonstrated quality improvement and not a
production model change. Champion 7.2.1, 7.2.1 research and standard fits remain
unweighted. Protected workflow/rollback/leakage gates are unchanged.

## Experiment
For **accuracy-7.2.2 only**, the chronological TRAIN partition chooses among
uniform labels, 365-day and 180-day exponential half-life. Each time-decay
variant uses age from the last match in its own fit partition, not machine time.
Weights are mean-normalized for comparable logistic regularization and are
passed identically to both orientations, the scaler, logistic estimator and
histogram gradient booster.

The choice uses an earlier TRAIN-only whole-day split (approximately 80/20)
and fixed, uncalibrated, symmetric 50/50 linear/boost probabilities on the same
validation fixtures. An alternative must improve pooled log loss by at least
0.002 and 1.96 standard errors of paired daily improvements, without Brier
regression. Otherwise retain uniform weighting. This is a conservative
**fit choice**, not proof of TOP-market improvement. Existing downstream
blend/calibration selection days and final holdout remain disjoint and untouched.
Serving refit can reuse the exact selected half-life, but only after separate
promotion approval. Metadata records the selection window, candidate metrics,
chosen half-life and actual fit anchor.

## Quality decision still required
Assess the immutable frozen report and candidate artifact against the pinned
7.2.1 champion. Re-evaluate on identical point-in-time priced winner fixtures
with real captured odds >1.50, ATP/WTA/Challenger strata, daily candidate
opportunity volume at the unchanged 60% threshold, days with >=5 opportunities
and proper scoring. Do **not** force five tips, impute unavailable odds, or
declare an untested market gate passed. Existing
`top_market_validation_required` fails closed.

## Execution and safety
Use `.github/workflows/protected-frozen-cdb-candidate.yml` only after PR CI
and a current global-writer/backup/snapshot preflight. The existing workflow
ensures freeze, verified restorable rollback, PIT leakage audit, candidate-only
fit and independent evidence persistence; it does not promote production.
One-shot merge-trigger training is gated by its exact approved commit prefix.
No tennis-provider API requests or CDB mutations are required.

Open evidence: no independent real-odds TOP-market replay or new frozen
training report yet. A successful fit alone cannot close this item.
