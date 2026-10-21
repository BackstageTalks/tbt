# ATP + WTA 7.2.1 — implementation-ready research handoff (2026-10-22)

**Status: CODE PREPARED / MODEL PROMOTION NOT APPROVED.**
This file is a reproducible morning handoff, **not** a claim of production
readiness, live-TOP profitability, new prospective evidence or permission to
change a serving model. Follow [promotion and rollback policy](MODEL_PROMOTION_ROLLBACK_POLICY.md).

## Frozen source scope

- PR #948: gated ATP-only Elo/linear/boost weights, with a disjoint later
  calibration-day acceptance test and pooled fallback.
- PR #949: optional count-backed serve/return strength and time-aware priors;
  no fabricated point denominators.
- PR #950: ATP opponent-strength and surface-adjusted recent form; no same-day
  look-ahead and zero impact on legacy production feature sets.
- PR #946: *research report only* for ATP versus WTA blend weights;
  does **not** turn on new WTA serving blend parameters.
- The `top-7.2.1` profile also includes available ATP leaderboard/rank history,
  WTA rank history and season features, plus guarded per-tour calibration.
  Legacy model artifacts retain their original semantics and fallback paths.

Both tours must be evaluated against the same preserved champion and Elo baseline.
WTA calibration and WTA input coverage require independent checks even when the
overall/ATP score is better. WTA blend selection remains diagnostic until
validated separately; do not present the #946 ablation as active WTA weights.

## Known data/evidence gap

The protected historical run
[39684498617](https://github.com/BackstageTalks/tbt/actions/runs/39684498617)
used an **older** source commit (`2b33bd7`), not the integrated #946/#948–#950
code. Its backup, leakage audit, fit and candidate-bundle remote readback
passed, but its final `publish_frozen_candidate_evidence.py` step failed with
`Independent persisted candidate comparison readback mismatch`.
The fix verifies the newly written evidence from its *immutable Git commit*
rather than a potentially stale default-branch content URL; tests explicitly
reject wrong blob identity or corrupted content.

**Therefore this older candidate is NOT deployable evidence for the final
integrated model.** Do not reuse its holdout as a new independent holdout, and
do not infer new forward-TOP performance from it.

## Morning execution, no production switch

1. Pin exact `main` SHA; confirm the evidence-persistence fix is merged and
   CI, offline calibration and WTA rank audit succeeded. Check current canonical
   writer lock and existing training runs; fail closed if unavailable or busy.
2. Prefer the protected existing workflow, via GitHub Actions
   [BlinQ protected candidate training](https://github.com/BackstageTalks/tbt/actions/workflows/protected-frozen-cdb-candidate.yml)
   with branch `main` and profile `top-7.2.1`. Alternatively use the
   repository's authenticated CLI: `python scripts/train_candidate.py start --ref main --profile top-7.2.1`.
   This freezes complete inputs, verifies the immutable backup, independently
   restores the champion, audits identity/leakage and fits a **new** candidate;
   it makes no production promotion.
3. Pin the returned run ID and attempt. Use `python scripts/train_candidate.py status --run RUN_ID`
   and `python scripts/train_candidate.py list`. Require successful
   `frozen-candidate-evaluation.json`, source manifest, candidate and champion
   hashes, independent downloaded candidate-bundle readback and signed Admin
   comparison. A finished CI workflow alone is not evidence of a valid model.
4. Inspect `training_report.json`: exact train/calibration/untouched holdout
   dates and identity counts; ATP/WTA `subgroups.tour` accuracy, log loss,
   Brier and calibration; confidence slices (75–80%, 80–85%, 85–90%);
   WTA rank/season coverage; ATP form and verified point-denominator coverage.
   Study `evaluation_model.tour_blend_experiment` separately from actual frozen
   serving weights and per-tour calibrator selection.
5. Require head-to-head same-fixture comparisons vs the stored production
   champion and Elo. The current nonpromoting gate in `scripts/pipeline.py`
   requires at least 200 holdout matches, >=0.001 log-loss improvement over
   both relevant baselines (when the champion exists), no >1pp aggregate
   accuracy drop, no >0.003 aggregate Brier increase, and ATP/WTA segments of
   at least 50 with at most 5pp accuracy, 0.03 log-loss or 0.015 Brier
   regression. Treat these as minimum safety gates, not proof of superiority.
6. Before *any* recommendation to activate, obtain **new** as-of pre-match
   real-odds and forward shadow evidence, with exact issuance timestamps,
   selection counts, calibration, accuracy, ROI, uncertainty and
   no missing/late pricing. Historical holdout accuracy is not live TOP ROI.
7. Independently rehearse champion rollback (artifact digest, full dependency
   set, repeatable restored predictions and health) *without* changing the live
   champion. Present exact proposed artifact SHA/version, evidence and rollback
   procedure for explicit operator authorization. Only then consider a
   separately approved production rollout and post-switch health/readback.

## Selection invariants (do not edit)

- **VALUE** priority comes before TOP, odds >=1.80, with symmetric two-way
  bookmaker odds difference <=15%.
- **TOP** minimum odds >=1.50, **no numerical daily cap** and no forced fill;
  never silently reintroduce the legacy ten-pick cap.
- No canonical CDB imports/mutations, provider requests, TOP/VALUE policy
  rewrites, champion replacement or automatic deployment belong to these
  research-only preparation tasks.

## Go / no-go record

| Workstream | Code | Real final-frozen evidence | Forward market evidence | Production |
| --- | --- | --- | --- | --- |
| ATP 7.2.1 | Merged research changes | **PENDING NEW PINNED RUN** | **NOT VERIFIED** | UNCHANGED |
| WTA 7.2.1 | Rank/season and guarded calibrator; blend ablation is report-only | **PENDING NEW PINNED RUN** | **NOT VERIFIED** | UNCHANGED |

**Decision:** prepared for a **nonpromoting** new research fit and readback;
**NO-GO** for model activation until the missing independent evidence and
operator-approved rollback gates are satisfied.
