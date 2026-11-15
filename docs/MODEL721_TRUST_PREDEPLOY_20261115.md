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
