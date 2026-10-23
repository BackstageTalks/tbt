# BlinQ 721 — strict three-way study protocol (2026-10-24)

This change adds **read-only comparison infrastructure**, not a fitted or deployable model.

## Immutable input expectations

- Original paired historical prediction file: champion and frozen 7.2.1 probabilities for the **same player orientation**, including the exact issued snapshot clock, immutable artifact identifiers and verified post-match settlement.
- Research probabilities: distinct model version and SHA, identical match/provider identities and original player orientation, recorded training and calibration cutoff, verified frozen input release SHA.
- Research must declare either `ISSUED_PREMATCH` (genuinely issued before original frozen capture) or `RETROSPECTIVE_PIT_REPLAY` (explicit historical replay). A replay must not claim issuance and must independently verify the as-of history state that existed before the original snapshot.
- Every settled match of the paired input must have a research prediction. Missing, duplicate or foreign IDs, future as-of inputs and wrong or missing timestamps fail closed.
- Training rows remain 2024+. Context from 2016–2023 may be used only when independently as-of verified and excluded from supervised model fitting.
- Absolute probability comparisons require identical test fixtures. High-confidence model subsets differ by model: report both selection accuracy and coverage, **not** only selected win percentage.
- No winner lookup is performed for missing outcomes; settlement is read only from the paired source.

## Usage

```bash
PYTHONPATH=scripts python scripts/audit_721_three_way.py \
  --paired /private/frozen-721-paired.json \
  --research /private/pit-replay-variant.json \
  --output /private/three-way-721-report.json

python -m pytest -q tests/test_audit_721_three_way.py
```

**Do not upload private raw paired predictions to a public repository or print individual match data in CI.**

The tool computes on equal fixtures:
- accuracy, Brier, log-loss;
- success and coverage among model-specific confidence >=80%;
- ATP/WTA and surface splits;
- daily-block bootstrapped paired 95% intervals against 7.2.1;
- strict identity and timestamp checks with explicit retrospective/prospective status.

## Existing evidence — not jointly comparable

1. Frozen candidate: [run 39986158547](https://github.com/BackstageTalks/tbt/actions/runs/39986158547), commit `0785626a06cbfa3a17dbac4ebde2845a8cb56d48`, n=9,559 paired champion vs 7.2.1.
2. Chronological variant study: [run 39991649667](https://github.com/BackstageTalks/tbt/actions/runs/39991649667), commit `e50b6579b6bdd3eb80fae71117e6b2c7d96fb23c`, n=180,419, pooled-vs-evidence-vs-specialist-vs-partial-pool on its own set.
3. The temporal report contains aggregate statistics and prediction fingerprints, **not the required per-match triplets**, and does not include the pinned production champion or frozen candidate on all of those 180,419 matches. A three-way winner cannot be inferred from these aggregates.

## Missing experimental execution

A **third true predictor series has not been issued or replayed** on the same original 7.2.1/champion fixtures. Do not represent the passing tool unit tests as a third model win. Create third-series probabilities through the project's verified-input gated research workflow with 2024+ fitting only, surface/opponent Gollub shrinkage, Glicko uncertainty and partial-pool ablations trained prior to the test cutoff. The existing model-protection and immutable backup gates must remain intact. Do not modify CDB, requests, public feed, or serving model.

The research output is only eligible for promotion review after a **new, untouched** holdout, tour/surface/competition checks, match winner accuracy, Brier, log-loss, >=80% coverage, leakage audit, real pre-start-odds evidence and independently verified restore/rollback. Production activation always requires explicit operator authorization.
