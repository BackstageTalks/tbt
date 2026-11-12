# BlinQ 7.2.2 — confidence and pre-match evidence study (2026-11-12)

**State: RESEARCH CODE PREPARED; NO NEW FIT, NO PROMOTION, NO DEPLOYMENT.**
This experiment uses the existing protected `accuracy-7.2.2` profile.
It does not replace 7.2.1, update the TOP policy, or consume tennis API quota.

## Why this is incremental, not a new model

- 7.2.2 already has guarded accuracy-blend selection, monotone calibration,
  disjoint PIT quality cohorts and ATP/WTA diagnostics (PRs #1399, #1405, #1406).
- Frozen training already computes paired unseen holdout scores, point-in-time
  availability flags, and a same-event shadow comparison.
- No further estimator, calibrator, Elo or serve/return feature semantics have
  been changed in this research change. The existing feature builder and
  snapshot lock remain authoritative.

## New reproducible output

The existing candidate fit (only for `accuracy-7.2.2`) now includes
`training_report.json:candidate_722_confidence_evidence`.

- Predetermined confidence bands: below 65%, [65%,70%), [70%,75%),
  [75%,80%), and 80%+. A probability equal to 65% enters [65%,70%).
- **Same-fixture** champion vs. candidate accuracy, Wilson intervals,
  mean confidence, realized-minus-predicted confidence gap, Brier and log loss.
- **Selection anchor:** frozen champion confidence, not candidate confidence,
  where a champion is available. This prevents silently comparing different
  event subsets merely because the new candidate changes probabilities.
- Breakdowns by ATP/WTA, surface (unknown stays unknown), pre-match paired
  serve/return availability, surface serve/return availability, both ranks,
  and tour × paired serve/return.
- The input flag counts are feature availability, **not** independently verified
  observation denominators, capture timestamps or freshness. Source freshness
  is explicitly `UNVERIFIED`. A fresh source-provenance audit is required.

The new section is **not** a training objective, confidence correction, TOP
ranker, selector change, or automatic promotion gate. No labels leave the
offline holdout; no predictions, raw rows or bookmaker quotes are published.

## Test and execution gates

Run code/contract regressions first:

```bash
PYTHONPATH=api:scripts python -m pytest -q \
  tests/test_candidate_722_confidence_evidence.py \
  tests/test_722_pit_evidence_calibration.py \
  tests/test_candidate_722_accuracy.py
```

For a future protected comparison, first verify the exact production champion
SHA, current global CDB writer lock, existing active trainings and a fresh
Model Factory preflight. Respect the currently locked Admin 7.2.2 profile until
the required champion release readback. Do not overlap another protected fit.

Use **only** the existing `protected-frozen-cdb-candidate.yml` with
`training_profile=accuracy-7.2.2`, `auto_shadow=false`, pinned `main`
commit after tests and review. The workflow freezes inputs, validates the
backup and leakage, fits only a separate candidate and persists aggregate
readback. Starting it is a separate operational step; this PR never dispatches
it and never switches the production model.

Before interpreting the candidate as better, require:
1. Exact same-fixture model and player orientation, immutable version+SHA,
   untouched chronological holdout with enough ATP and WTA observations.
2. Aggregate and subgroup accuracy, log loss and Brier compared with 7.2.1
   *and* Elo; confidence 65%+ coverage and Wilson intervals, not cherry-picked
   successes. Use the repository's established promotion thresholds.
3. True original pre-match input timestamps and point denominators for
   serve/return, surface and ranking. An available post-match CDB value is not
   acceptable PIT evidence.
4. Fresh forward issued/settled shadow comparison, true pre-start bookmaker
   quotes for any separate TOP/ROI study, and independent rollback rehearsal.
5. Explicit operator approval before any champion promotion.

**Remaining work:** actual fit+evaluation, original-source PIT freshness audit,
independent forward evidence and deployment decision. No measured performance
gain is asserted by this preparation.
