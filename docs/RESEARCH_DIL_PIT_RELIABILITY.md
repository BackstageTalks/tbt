# BlinQ — DIL pre-match evidence + TOP/VALUE reliability research (2026-10-23)

**Status: research-only; NOT trained, merged, activated, or deployed.**
The serving champion, CDB V1, DIL V2 imports and current TOP/VALUE market selection remain unchanged.

## Why this change

Existing `FeatureBuilder` already supports historical surface form, opponent-adjusted form, serve/return estimates, event level and workload. Training profile `top-7.2.1` already enables point-weighted serve/return and ATP surface-opponent form, while prior rich-charting ablations were not robust. Do not claim these are entirely new.

`api/tbt/models/evidence_lab.py` is a small isolated research contract for **new independently verified DIL observations** and quality-based abstention, not a competing source of canonical identity.

## Inputs and invariants

Each `HistoricalEvidence` row refers to one canonical player in one independently reviewed canonical match and carries:

- tour, canonical player/match IDs, exact match completion timestamp;
- evidence `available_at`, and the historical opponent probability's independently pre-result `expected_recorded_at`;
- original per-match integer service/return/break-point counts with missing values retained as NULL;
- reviewed cross-source identity flag. A metadata flag is **not** a substitute for verification by the upstream `til_v2.link` evidence workflow.

Reject unreviewed player/match identities, impossible raw counts, future-fitted opponent probabilities, duplicate canonical matches, naive dates or contradictory coverage. Historical rows are eligible only when the completed match's UTC day is *strictly* before the prediction day **and** statistics were available by issuance. This intentionally forgoes same-day information when exact ordering cannot be guaranteed.

The feature projector exposes prior-20-point-weighted service, return, second-serve, break-point save/convert rates plus residual historical opponent-adjusted form, shrunk surface residuals and **observed** coverage. Empty denominators stay NULL. No same-match result is used.

The proposed reliability filter is **abstention only**. It evaluates the weaker player for recent and surface depth, the weakest coverage across five stat families, and disagreement across at least two real model probabilities. The returned `evidence_score` is an explanatory heuristic, **not** calibrated accuracy, betting probability or suggested coefficient for the serving model. Missing model disagreement blocks inclusion, never assumes perfect model agreement. Thresholds are research hypotheses, not authorized live TOP/VALUE filters.

## Validation and advancement

Synthetic deterministic local validation: `PYTHONPATH=api pytest -q tests/test_evidence_lab.py` — 8 tests passed on the isolated implementation. GitHub CI/branch test execution remains separately unverified until a runner executes.

Before any candidate fit or selection policy change:

1. Independently reviewed DIL→CDB match AND player IDs, actual source-as-of timing and historical pre-match opponent expectations must be available. The 577-source intake by itself does **not** satisfy this; unlinked source observations are not eligible.
2. Export a run-bound immutable cohort and sidecar from the existing private protected training path. Verify canonical match/player identities, timestamps, source hashes, and strict prior-day feature replay before a training fit.
3. Compare baseline, original 7.2.1 and opt-in evidence features on multiple rolling chronological windows. Keep the previously inspected holdout untouched. Report ATP/WTA and main/Challenger/ITF stratification; measure coverage/abstention, Brier/log loss/calibration, TOP/VALUE yield and realized results on fixed issued candidates; use non-overlapping pre-declared tuning and final windows.
4. Gate any actual fitting on the established immutable-input + champion restore safety workflow. Never promote production without explicit owner approval, independent shadow read-back, and tested rollback.

No live model improvement, selectivity gain or win-rate benefit can be asserted from synthetic unit tests.
