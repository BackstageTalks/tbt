# BlinQ 7.2.1 — paired sports ranking evidence protocol (2026-11-16)

## Objective and non-negotiable rules

Product goal: ideally at least three high-quality TOP winner picks per day, **no maximum and no forced minimum**. Only sports data may drive the winner prediction and its ranking. Historical pre-start odds are admitted exclusively as a later minimum **1.50** filter. No PROMO/ACES changes, no bookmaker-derived feature, no EV/value/ROI target, and no production model replacement without verified improvement on real TOP issuance.

## Confirmed starting evidence

- Production model frozen SHA-256: `c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91`.
- Previous 2026-11-16 frozen candidate `blinq-candidate-frozen-43791051682-1` SHA-256 `f6fbc34a1d9786e6c455e4cb556e025270c2fb4ef60a33c31fef6a0b9b0c48f7`, readback verified in private `audit/model-frozen-candidate-latest.json`.
- On 7,107 same-fixture offline holdout rows, candidate accuracy 70.21% vs 69.49%, ROC AUC 0.7720 vs 0.7679; candidate ECE worsened 0.01479 vs 0.01059. These metrics do **not** prove a better >=1.50 TOP selection.
- Latest persisted training evidence explicitly blocks production promotion on `top_market_validation_required`.
- The previous frozen release stored aggregated metrics only. Its per-fixture output cannot be retroactively reconstructed from aggregates.
- Morning selection funnel PR #1646 is an independent read-only quote-depth audit, still open at this protocol's start.

## New isolated research implementation

1. A candidate **future** protected fit serializes the *exact* eligible chronological holdout frame paired with champion/candidate predictions, rechecks winner-side orientation, unique IDs, UTC times, actual labels, the shared pre-match feature frame and feature-vector SHA-256. Versions and holdout fingerprint are explicit.
2. The scored rows go only to the **private immutable candidate release** as `paired_top_holdout.json.gz`. Remote release-store bundle checks plus independent row/digest readback are required before writing the private aggregate attestation. No row-level data enters public repository or routine workflow artifact.
3. A separate read-only script accepts a verified historic pre-start quote on the same oriented fixture, applies sport-derived confidence/depth/surface gating **first**, then side-matched real odds >=1.50, then ranks daily top 3/5/7 and all qualified. Its summary reports both winner ROC AUC and confidence-vs-correctness AUC, including no-pick days. It labels itself research rather than native issued TOP, and refuses ambiguous quote identities.
4. No changes to the serving ensemble, public confidence, TOP production eligibility, current private CDB or champion. The changed evaluation/reporting logic is **not an improvement claim**.

## Pending before a model-logic decision

- Run focused and full protected CI on this branch, check any regression or identity failure, and verify private release readback after the next authorized fail-closed training execution.
- Attach actual time-proven odds from an independently checked source to the emitted scored rows. Do not treat missing quotes as sub-1.50 prices or invent missing settlements.
- Audit feature coverage and pre-match provenance by competition and surface. Evaluate predefined sport-only candidate model variants with a separate fit/selection period; keep the already inspected 2026-10-27 through 2026-11-15 holdout labelled retrospective.
- Measure uncertainty by betting day, identical fixtures, real publication eligibility and later prospective shadow TOP issuance. Decide champion switch only when measurable gain and rollback requirements are met.

**Decision:** keep production champion; research branch only until all gates above are proven.
