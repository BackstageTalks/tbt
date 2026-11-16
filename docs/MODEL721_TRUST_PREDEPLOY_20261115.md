# BlinQ 7.2.1 — count depth versus model trust (15 November 2026)

## Scope and status
Research patch only. Serving champion stays v7.2.1; no fitting, provider calls, CDB writes, historic regrading, Telegram delivery or model swap. PROMO and candidate 7.2.2 are explicitly out of scope.

## Confirmed diagnosis
- data_depth is min(history count of the two players, 50)/50 and reaches 1.0 after 50 historical matches each. It does not certify serve/return completeness or empirically validated predictive reliability.
- Serving model already uses isotonic calibration and contains missing-statistics feature flags; the reported problem is not a lack of all calibration. Artifact model SHA c1e761ccc3e530c600abc8559031869071dddef99e9a5fffb78ed602cb933c91; this inspection is reported by supplied Codex artifact, not independent production live read-back.
- Supplied exact issuance audit (90-day window, single serving-model version, verified pre-deploy publication snapshots): 57 published TOP, 51 settled, 30W/21L, 58.82% hit rate against 76.23% mean recorded confidence, Brier 0.27845. This is a small selected cohort; confidence calibration warrants review before deployment claims.
- Read-only candidate-snapshot replay (36 available dates but only 2,044 eligible pre-match candidates and 7 comparable current-model dates; 13,072 rows without usable prematch time) cannot substitute for a clean holdout or public issuance. Its sample is biased by outcome/availability selection. No odds, ROI or post-match features may enter the sports ranking.
- Confirmed 13 November Zverev–Jodar PRIME publication has raw/public 76.46%, history depth 1.0, 881/147 overall and 509/103 hard-surface observed matches, both serve/return flags present; odds 1.380228 are outside TOP >=1.50. This is an offer/price gate, not proof of data scarcity. Reproduce other major matches separately from exact issued snapshots.
- User requested Shelton–Fils and Zverev diagnostics; no same-event contemporary release evidence was independently read here, therefore neither missing-data nor selection explanation is asserted for those fixtures.

## Patch behavior
- Keep the existing historical data_depth and public-depth-shrink mathematics, but stop describing the history count as probability_reliability. Publish null trust + explicit history-count depth and reliability status.
- Record point-in-time retained-window paired serve/return coverage, recency and effective sample, not alleged career-long evidence.
- Persist price-independent sports prediction audit in private selector candidate snapshot; reject invalid identity, invalid p and non-prematch evidence, deterministic deduplication.
- Allow all already-qualified TOP entries instead of imposing a count-of-three cap; 3 remains a daily objective, never an enforced minimum. Existing eligibility rules and VALUE priority remain intact. This can increase live issuance, therefore keep changes on PR until full CI, feed/readback checks, and owner-approved release decision.
- Rank selected TOP by competition and model score, using history counts only as tie-breakers; no bookmaker consensus as sports confidence.

## Verification and release gate
- Original Codex bundle reports 172 local tests and JavaScript syntax/preflight passing over its older checkout; not independent validation of this rebased branch.
- Require full branch CI, focused tests, metadata parity, authorized tier checks, unchanged VALUE/ACES, and private snapshot read-back before considering merge.
- Accuracy uplift is **NOT ESTABLISHED**. Before any recalibration train/fitting or champion change: immutable training input, rollback backup read-back, PIT leakage checks, validation-vs-holdout split, per-tour/quality calibration and objective comparison with the fixed serving model. No arbitrary confidence threshold changes.
- PROMO/7.2.2 not part of this patch.

## Independent aggregate cross-check (2026-11-15; retrospective, not a recalibration)

The following recomputes aggregates from the user-supplied immutable
`BlinQ-issued-top-current.json` and `BlinQ-model-diagnosis.json` reports,
not from a fresh serving API read-back or individual raw match records.

- Exact published 7.2.1 TOP: 57 published, 51 settled, 30W/21L,
  **58.82%** accuracy (95% Wilson descriptive interval **45.17–71.25%**)
  against **76.23%** average issued probability, **-17.41 percentage
  points** observed minus forecast; Brier **0.27845**. This is a
  *selected issued cohort* and must not be relabelled overall model accuracy.
- Its settled competition mix is **26 ITF, 19 Challenger, 4 ATP, 2 WTA**.
  Only **5/51** have verified paired serve/return availability in the
  report; the other **46 are unverified**, **not proven missing**.
  The separate `stats=yes` field for 51/51 is *not* equivalent to
  verified paired serve/return evidence.
- The separate 266-match same-capture shadow sample has 7.2.1 accuracy
  **176/266 = 66.17%**, mean confidence **67.67%** and Brier
  **0.21570**. Neither its sampling frame nor its published/issued
  status matches the 51 settled TOP rows; do not infer causation or an
  unbiased global calibration correction from this contrast.
- On champion-confidence anchored, **same-event** shadow bins:
  **>=70%** contains 111 matches with 85 correct for **both** models;
  **>=80%** contains 60 matches with 49 correct for **both** models.
  This does not establish any 7.2.2 uplift. An exact **>=65%**
  result **cannot** be reconstructed from the exported 60–70% band;
  the separate read-only diagnostic in PR #1570 now computes an
  inclusive 65% aggregate only when scored row-level holdout is available.

**Release guard:** the success of CI, the 172 earlier local tests, or the
higher retrospective candidate-pool hit rate does **not** establish a repaired
7.2.1 calibration. The current production champion and TOP offer policy remain
untouched until a frozen, time-separated, identity-verified point-in-time
evaluation proves the effect on the actual issued population. Do not fit a new
calibrator on this issued cohort and then evaluate on the same 51 outcomes.
The TOP count-cap removal in this PR changes future issuance; never merge
this draft solely on the strength of these aggregates.

## Release action — Codex 7.2.1 exact-scope UI deployment

The original scope was merged in PR #1632 at commit
`76b7789c2029393c80360938b58ad34030a1bdab`.
Its full PR CI succeeded (run 43756074512); the main-commit read-only
selector-reliability replay succeeded (run 43763114243). The checked-in
model artifact was not replaced. This source-only administrative status
update requests the existing explicit Azure UI/API deployment workflow;
it must pass the workflow's stamped SHA and exact live-asset hash read-back.
No model training, promotion, PROMO change, provider calls or CDB writes
are authorized by this deployment note.

## Verified quote-identity coverage fix #1644 — 2026-11-16

Merge `a56a96dfb770f36acc30c907dabc384adfee8c06` only improves
full-pair surname-first initial matching with ±45-minute time validation,
unique event identities and fail-closed ambiguity. It preserves the 7.2.1
production model, untouched probabilities, TOP >=65%, min actual odds 1.50,
ITF/identity/evidence guards, other markets, CDB and PROMO. Its focused
tests, PR-wide backend/browser checks (run 43828556737) and morning safety
check (run 43828556788) succeeded. A fresh production watchdog (run
43829830191) independently detected the stale Azure serving copy of
`api/tbt/services/propline_live.py`; live deployment of the merged fix is
therefore still required.

Today's immutable morning refresh report (run 43802991954, generated
2026-11-16 UTC) contains 786 upcoming matches, 1 TOP, 0 VALUE. The primary
match-winner odds cache returned no quotes for 82 candidates. The separate
PropLine read-only audit logged 438 events on board, 263 matches and 253
valid two-way Match Winner quotes. These are distinct populations and cannot
be added. Improved odds coverage does not establish new TOP picks or better
sports prediction accuracy; future production read-back must measure gain.

**Deployment gate:** request existing Azure UI/API release with exact SHA
and live hash check; source-only note triggers no provider calls, training,
model promotion, CDB writes, TOP-rule change, UI redesign or offer rebuild.
