# BlinQ — DIL pre-match evidence + TOP/VALUE reliability research (2026-10-23)

**Status: research-only; NOT trained, merged, activated, or deployed.**
The serving champion, CDB V1, DIL V2 imports and current TOP/VALUE market selection remain unchanged.

## Why this change

Existing `FeatureBuilder` already supports historical surface form, opponent-adjusted form, serve/return estimates, event level and workload. Training profile `top-7.2.1` already enables point-weighted serve/return and ATP surface-opponent form, while prior rich-charting ablations were not robust. Do not claim these are entirely new.

`api/tbt/models/evidence_lab.py` is a small isolated research contract for **new independently verified DIL observations** and quality-based abstention, not a competing source of canonical identity.

## Inputs and invariants

Each `HistoricalEvidence` row refers to one canonical player in one independently reviewed canonical match and carries:

- tour, canonical player/match IDs, exact match start and completion timestamps;
- evidence `available_at`, and the historical opponent probability's independently **pre-start** `expected_recorded_at`;
- original per-match integer service/return/break-point counts with missing values retained as NULL;
- reviewed cross-source identity flag. A metadata flag is **not** a substitute for verification by the upstream `til_v2.link` evidence workflow.

Reject unreviewed player/match identities, impossible raw counts, future-fitted opponent probabilities, duplicate canonical matches, naive dates or contradictory coverage. Historical rows are eligible only when the completed match's UTC day is *strictly* before the prediction day **and** statistics were available by issuance. This intentionally forgoes same-day information when exact ordering cannot be guaranteed.

The feature projector exposes prior-20-point-weighted service, return, second-serve, break-point save/convert rates plus residual historical opponent-adjusted form, shrunk surface residuals and **observed** coverage. Empty denominators stay NULL. No same-match result is used.

The optional candidate training adapter `api/tbt/models/evidence_training.py` adds 10 namespaced, orientation-correct numeric features to a frozen cohort without changing the current model feature schema. It uses an indexed, completion/availability-bound history and independently crosschecks all CDB fixture identities, UTC times and target row ordering. If a `prediction_as_of` field is supplied, every historical lookup is cut off at the genuine issuance time; without this field the calculation is only a pre-match-start research simulation, not evidence about historical published selections. Absent reviewed DIL player/match crosswalk or informative paired service/return evidence, it refuses to enable a research fit. The adapter itself does not start a fit.

The proposed reliability filter is **abstention only**. It evaluates the weaker player for recent and surface depth, the weakest coverage across five stat families, the minimum actual service/break-point opportunity denominators and disagreement across at least two real model probabilities. The returned `evidence_score` is an explanatory heuristic, **not** calibrated accuracy, betting probability or suggested coefficient for the serving model. The model-disagreement input requires at least two separately identified estimators, each reporting probability for the *same canonical left player*. A player's complementary 80%/20% probabilities from one model do not constitute an independent ensemble. Missing model disagreement blocks inclusion, never assumes perfect agreement. Thresholds are research hypotheses, not authorized live TOP/VALUE filters.

## Validation and advancement

Branch validation: the original implementation passed the full GitHub backend test step in CI run `39957460351` (subsequently completed successfully). The current extended code and tests must pass a newer branch-head CI run; this sentence does not claim they have. Run `PYTHONPATH=api python -m pytest -q tests/test_evidence_lab.py tests/test_evidence_training.py` to verify the 22 focused regression tests.

Before any candidate fit or selection policy change:

1. Independently reviewed DIL→CDB match AND player IDs, actual source-as-of timing and historical pre-match opponent expectations must be available. The 577-source intake by itself does **not** satisfy this; unlinked source observations are not eligible.
2. Export a run-bound immutable cohort and sidecar from the existing private protected training path. Verify canonical match/player identities, timestamps, source hashes, and strict prior-day feature replay before a training fit.
3. Compare baseline, original 7.2.1 and opt-in evidence features on multiple rolling chronological windows. Keep the previously inspected holdout untouched. Report ATP/WTA and main/Challenger/ITF stratification; measure coverage/abstention, Brier/log loss/calibration, TOP/VALUE yield and realized results on fixed issued candidates; use non-overlapping pre-declared tuning and final windows.
4. Gate any actual fitting on the established immutable-input + champion restore safety workflow. Never promote production without explicit owner approval, independent shadow read-back, and tested rollback.

No live model improvement, selectivity gain or win-rate benefit can be asserted from synthetic unit tests.
