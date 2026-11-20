# 2026-11-20 — Match Winner market-anchored calibration research

**State:** PREPARED only. Research source + synthetic tests; no production predictor, selector, VALUE, PRIME, ACCA, model binary, CDB, external scheduler, API budget or public probabilities changed.

**Goal:** test whether a market-anchored probability improves *correct-winner prediction*, never expected value or bet pricing. This is a deliberately separate read-only experiment, not a replacement for the sports-only calibration draft #1669 or TOP ranking draft #1652.

## Verified immutable source selection and leakage
Input user exports (not committed): blinq_vysledky_2026-11-20.csv, utf-8-sig, semicolon separated. Include settled match_winner only, dedupe (Event_ID, Výber_ID). 1,140 unique; 945 with exact issued_snapshot.betting.fair_implied_probability, 195 excluded from market fitting/validation (never substitute 1/odds). All 945 had parseable timezone-aware captured_at and issued_at strictly before scheduled match date, captured_at <= issued_at; 0 timestamp violations. Time parser must handle mixed ISO precision.

Chronological day-disjoint fit 574 rows ending 2026-11-05; test 371 beginning 2026-11-08. GroupKFold by week is secondary retrospective diagnostic **not** forward-chaining prospective proof.

## Exact executed metrics (2026-11-20)
| Test on 371 rows | log loss | Brier | winner accuracy | ECE10 |
| --- | ---: | ---: | ---: | ---: |
| Original p | 0.451854 | 0.141839 | 0.814016 | 0.022349 |
| Issued pre-match fair | 0.425709 | 0.131532 | 0.827493 | 0.069399 |
| Unconstrained logistic M4, L2 C=1 | 0.413025 | 0.127554 | 0.830189 | 0.022922 |
| **Symmetric research-only adapter** | **0.416365** | **0.128480** | **0.832884** | **0.036244** |

Frozen research coefficients, fit rows only: a=0.058883431874891985, b=1.5190747404944331, c=-0.12775926576102908. These are NOT production calibration parameters. Note full-data descriptive/unregularized fits can produce a NEGATIVE model coefficient, so a monotonic constraint is required.

Original M4 with intercept is NOT symmetric under swapping selected player and opponent; this adapter averages the two oriented logistic probabilities:
q = 0.5 * [sigmoid(a*logit(p)+b*logit(fair)+c) + sigmoid(a*logit(p)+b*logit(fair)-c)].
Only non-negative a,b allowed. Independently evaluated 2,000 row-bootstrap differences for this exact symmetric adapter:
- delta log loss vs model = -0.035489; 95% CI [-0.062567, -0.007972].
- delta log loss vs market = -0.009344; 95% CI [-0.034593, +0.015831]; **not proven** to improve over market.
- ECE10 vs original increased 0.022349 -> 0.036244; **calibration non-regression not met**.

Original 1,140 settlement set is selected/published only, heavy ACCA. Thus TOP-only holdout has just 33 price-known rows (18/33 wins), Value 14 (5/14). No full-slate counterfactual publication is possible from the issued-only export. Do not tune threshold policy on these test outcomes.

## Code contract and rollback
- New standalone api/tbt/models/market_shadow_calibration.py is unreferenced by production serving and not activated by any pipeline. Missing price or missing/stale/future captured/issued/start time -> untouched model p, explicitly reported by return_fallback_mask.
- Only timezone-aware captured_at <= issued_at < scheduled_at is accepted. Missing/invalid probabilities fail closed.
- Side swap symmetry q(p,f)+q(1-p,1-f)=1; monotone in both probabilities for a,b>=0.
- New tests in tests/test_market_shadow_calibration.py: 7 focused PASS locally on the exact Git blobs (module SHA 4ab1bcbbf3a4e9f26432ac065e59541ef65c4f4e, test SHA cf49a26e3c4fb3e19d109b91448fcf52e27c4dea). Full branch CI not yet independently confirmed.
- Rollback: close draft PR or discard branch; no production state to restore, no new backups required for this read-only evaluation.

## Remaining gate
Do not merge/activate/promote. Need exact-head CI, forward-in-time and day-block-bootstrap accuracy & ECE non-regression on genuinely new fixtures, adequate ATP/WTA + TOP subgroup evidence, independent two-way issued-quote provenance, champion parity and a separate explicit operator decision. No provider or canonical writes.
