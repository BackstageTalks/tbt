# BlinQ Match Winner paired market shadow

The existing private 7.2.1 shadow predicts the same fixtures with two models. It captures before odds enrichment, so a quote seen later cannot demonstrate a three-way comparison at the original shadow cutoff. The paired market shadow takes a new receipt after the existing odds enrichment, with the raw predictions still tied to the same inference clock. It uses the existing monthly candidate archive and writer. The receipt contains no outcomes or public issuance claims.

## Scope

- Compare the serving champion, the active challenger, two-way market fair probability, the count-depth-adjusted champion and two fixed 80/20 logit blends. Track results by exact model versions and SHA-256, tour, low-depth cohort, TOP, ACCA and VALUE. Category cohorts use the current selector's same-run membership before carry-forward. They measure probabilities for the same picks. The separate market-rank shadow continues to measure counterfactual selection.
- Replay TOP market veto thresholds of 50%, 55% and 60% without replacing removed picks. Report eligible, kept, settled and priced flat-stake ROI. The veto is applied only to the captured priced TOP cohort.
- Require both sides of a single bookmaker quote, compatible price and fair probability, exact match/event/player orientation and start across predictions, and at least ten minutes' lead from the real post-enrichment observation clock. The source quote clock is retained as provenance. Some providers use a synthetic selection time, so the observation clock is the pre-start guarantee.
- Preserve the first priced event within each artifact pair. Report readers verify the receipt digest, deduplicate across included monthly archives and settle only from the existing canonical identity join. Withdrawals, missing results and ambiguous joins do not enter log loss or ROI. The refresh report covers the current and previous monthly partitions and uses an independent manifest and byte read-back. Confidence intervals resample UTC match days and are descriptive, especially for few days.

## Evidence for the experiment

| Historical diagnostic | Sample | Result |
|---|---:|---|
| Champion / market / 80:20 on the same priced fixtures | 333 | Log loss 0.53005 / 0.51960 / 0.51571 |
| Current adjusted champion / unadjusted on depth below 0.50 | 115 | Log loss 0.62281 / 0.43403 |
| ACCA market / fixed 80:20, chronological replay | 726 | Log loss 0.36317 / 0.36075 |
| TOP baseline / fair >= 0.60 without refill | 149 / 45 | ROI -16.21% / -5.85% |
| November 25 candidate / champion on identical unpriced holdout | 9,623 | Log loss 0.55780 / 0.57135 |
| November 25 candidate / champion / market at one cutoff | 0 settled | Await genuine new paired outcomes |

The diagnostics use the submitted CSV exports and the private November candidate archive. The priced historical samples do not establish prospective performance. The player-ace count prototype improved MAE on 93 matched observations (4.40 to 3.58). The set/game prototypes did not improve MAE in their paired samples, and double faults had only four comparable observations. These projection experiments and candidate time-decay training remain separate from the Match Winner capture.

## Running and reviewing

The repository variable `TBT_PAIRED_MARKET_SHADOW_ENABLED=true` opts an existing, authorized refresh into capture. The workflow restricts it to `refresh`, `current-refresh`, or the existing explicit refresh trigger. Code merge alone leaves capture off. No provider requests or model training are added by the paired capture. The challenger comes from the existing private active-candidate asset. Its GitHub asset digest matched the November 25 frozen candidate at review time. Verify the version and digest in the first real receipt before using the cohort for the November 25 decision.

Look for `paired_market_capture`, `paired_market_readback` and `paired_market_comparison` in the refresh log. A successful capture is evidenced by `PRIVATE_READBACK_VERIFIED` and both digests. For a mature comparison, reach at least 400 settled priced pairs and review the number of days, ATP/WTA counts, paired log loss and Brier, calibration on TOP and ACCA, veto coverage and uncertainty. The threshold is a review checkpoint. Promotion and public rule changes require separate decisions.

Turn the variable off to stop captures. Existing private receipts remain available.
