# BlinQ 7.2.1: high-confidence calibration repair (2026-11-15)

## Intended change
The existing 7.2.1 serialized champion uses an isotonic calibrator and can
produce repeated probability plateaus. The earlier candidate profile
`top-7.2.1` already restricts new global maps to identity/monotone Platt, but
chooses by overall log loss and identity-relative overall Brier. This can
still accept a calibration map that makes the high-confidence (>=65%) subset
less reliable despite improved average scores.

This change adds a **frozen raw-confidence, inclusive 65% selection gate** to
new `top-7.2.1` research candidate fitting. Every proposed smooth map
must have both no-worse Brier and no-worse log loss than raw identity on the
*same* high-confidence fixtures on later **calibration selection days**.
It must still pass the existing overall Brier gate. If fewer than 100
high-confidence observations exist, keep identity and mark the evidence
insufficient. Fit weights and calibrator type remain selected entirely before
the untouched final holdout. Prediction symmetry and the existing published
champion's binary are unchanged.

The 65% anchor is raw, not candidate-adjusted confidence, so an overconfident
candidate cannot hide mistakes by moving them below the category cutoff.
No bookmaker quotes, odds, result-lagged source features or newly discovered
holdout labels enter the calibration.

## Source evidence / guardrails
- Current published 7.2.1 TOP issued cohort: **51 settled; 30 won; 58.82%**
  vs **76.23%** mean issued prediction; mostly ITF/Challenger. Publication
  cohort is small, selected, and cannot be reused as a calibrator fitting set.
- Frozen candidate report `tbt-data:audit/model-frozen-candidate-latest.json`
  from 2026-11-06: 3,621 untouched test matches, existing candidate log loss
  0.566963 vs serving 0.567299 (delta -0.000336), Brier 0.193085 vs
  0.193064 (worse +0.0000205), ECE 0.015327 vs 0.006153 (worse).
  **The existing candidate is not promotable.**
- `tbt-data:audit/model-promotion-readiness-latest.json` verified
  7,087 unseen results across 19 whole UTC days as of 2026-11-15 12:55Z,
  with production artifact SHA c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91.
  These counts are *availability*, not proof of a winning calibrated model.

## Acceptance / rollback
1. New synthetic tests and all repository CI pass; read back exact head SHA.
2. Existing global writer lock and frozen candidate backup/readback must pass.
3. Fit a **separate** 7.2.1 candidate with existing
   `.github/workflows/protected-frozen-cdb-candidate.yml` and
   `training_profile=top-7.2.1`, using **zero tennis provider requests**.
4. Compare candidate/production on the **same untouched PIT holdout**, plus
   ATP/WTA, serve/return evidence cohorts, and **champion-anchored 65%+**.
   Training report `pit_evidence_holdout.same_fixture_top65` now records the
   *same* held-out fixtures for both models with accuracy, mean confidence,
   calibration gap, Brier, log loss and paired deltas. This is evaluation
   evidence only, never training input or automatic promotion.
   Reject if Brier, log loss, accuracy or appropriate subgroup gates regress
   under established promotion rules. Do not fit calibration on published TOP
   and also evaluate on those 51 same results.
5. Only the verified, backed-up exact candidate may be promoted after release
   gate and fresh pre-match shadow; otherwise leave the champion unchanged.
6. Any release regression: restore the exact previous model artifact with
   backup/readback via established protected rollback, not a manual writer.

**Status:** Research source/test change only. A PR/CI pass cannot substantiate
an accuracy or profitability improvement. No TOP/ESÁ/VALUE/VIAC ES policy,
web UI, Telegram, CDB or PROMO change is included.
