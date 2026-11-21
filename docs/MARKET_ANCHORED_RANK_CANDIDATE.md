# Market-anchored Match Winner rank — candidate only (2026-11-21)

**STATE: PREPARED research candidate. NOT an approved champion promotion.**
`AGENTS.md` applies. No retraining, CDB write, provider API sweep,
production offer activation, or TOP/PRIME eligibility change by default.

## Goal and immutable constraints

Only reorder existing qualified TOP/PRIME/VALUE cards. Preserve native:
`probability`, bookmaker odds, eligibility thresholds, selection exclusivity,
category quotas, champion model artifact, and CDB values.

Candidate sorting value:
```
q = sigmoid(1.102 * logit(valid_prestart_fair) - 0.009)
rank_probability = sigmoid(0.8 * logit(q) + 0.2 * logit(public_model_p))
```
If the selected side lacks finite valid fair with `betting.captured_at <
scheduled_at`, **rank_probability = original model p**, with
`rank_source=model_fallback`. The script does not pretend post-match odds
were captured before match start. `rank_probability` is only an ordering
score: do not replace public `probability` or requalify rejected cards.

Research provenance: ATP Oddstrader 2016–26 historical slope/intercept
1.102/-0.009 on a *claimed* 45,903-match source cohort; opener 1.088/-0.008
on a *claimed* 36,972. Neither source fit was independently reproduced
from raw point-in-time bookmaker snapshots in this candidate PR. WTA fit
is **NOT VERIFIED**. 0.8/0.2 weights are proposed, NOT trained on
an untouched holdout.

## Separate safety switches — both default OFF

In existing authorized GitHub `data.yml` refresh environment:

| Behavior | Owner-approved gate | Selected value | Default |
|---|---|---|---|
| Market-anchored ordering | `TBT_MARKET_ANCHORED_OWNER_APPROVED=true` | `TBT_RANK_SOURCE=market_anchored` | `model` |
| Emergency TOP fill | `TBT_TOP_EMERGENCY_FILL_OWNER_APPROVED=true` | `TBT_TOP_EMERGENCY_FILL=true` | `false` |

**Both conditions must hold** to turn each option on. Merge alone cannot
activate a new selector even if only the original selection variable has
previously been set. The second option is a separate PRODUCT POLICY
change (floor 0.60 exception), not approved by this candidate. It does NOT
fill PRIME. Do not switch it on without a separate explicit owner decision.

Existing A0 shadow and its separate gate
`BLINQ_MARKET_A0_OWNER_APPROVED` are unchanged.

Rollback after an explicitly approved trial: unset the approval variable,
confirm the refresh's `TBT_RANK_SOURCE=model` or
`TBT_TOP_EMERGENCY_FILL=false`, then run the original authorized refresh.
This is NOT a new cron or an invitation to spend extra API quota.

## Observed retrospective same-N replay

Input: `blinq_vysledky_2026-11-20.csv`, 1,140 unique issued
Match Winner tips across 44 UTC dates. This is a selected-only sample,
NOT the entire fixture board and NOT a prospective independent cohort.

The submitted replay mistakenly used the default pandas
`pd.to_datetime()` parser on mixed-format timestamps, reporting only
649 usable prestart prices. Correct `format="mixed", utc=True` yields:

- **945 pre-start fair** (83% of 1,140), **195 original-model fallback**.
- TOP-like (p≥0.60, odds≥1.50, top 3/day), N=121:
  champion **52.1%**, candidate **60.3%**, delta **+8.2 p.p.**,
  95% day bootstrap **[+1.8, +14.6]**.
- PRIME-like (p≥0.68, odds<1.50, top 10/day), N=429:
  champion **89.0%**, candidate **91.1%**, delta **+2.1 p.p.**,
  95% day bootstrap **[-0.2, +4.4]**.
- Matched daily selection counts retained for both heuristics;
  the *replay's* non-inferiority CI gate lower bound > -1 p.p. passed.

**No claim of live winner improvement.** The model choice and replay use
the same time period; the candidate has no frozen full-slate input. A
winner-pick improvement over raw fair market is not demonstrated,
and the TOP-like/PRIME-like labels are approximate—not true
policy-reproduced section assignments. Previously observed 945
issued picks: BlinQ 755/945, raw market 764/945; market-only
calibration 760/945; do not conflate a small top-N ordering proxy
with improved calibrated probabilities.

Reproduction:
```bash
python scripts/candidate_replay_report.py /path/to/blinq_vysledky_2026-11-20.csv
PYTHONPATH=api:scripts python -m pytest -q tests/test_market_anchored_rank.py
```

## Gates before any production activation

1. Green CI on the exact PR head and independent `main` diff read-back.
2. Stable default-off selection and invariant tests; same number of qualified
   cards and unchanged public model `probability` with the flag off.
3. Independent prospective, full-slate shadow comparison with capture/quote
   times and same-N daily ranking; B2 minimum 400 valid paired matches and
   daily A0 issuance evidence before stronger inference.
4. Separate explicit owner approval for ranking and, if desired,
   emergency TOP product-policy change.
5. Real authorized refresh with frozen prestart evidence, read-back
   and latency/lock/API budget monitoring. Roll back on increased errors,
   changed public eligibility, bad provider provenance or regression.

**Merge of default-OFF research implementation is not activation**.



## 2026-11-21 follow-up: optional TOP market-side veto

The owner supplied a second ZIP (`candidate_market_anchored_rank2.zip`,
SHA256 `60b872915c47de57d1ecca1756dfbe9e75d6b032250530e6614b48ae7778c241`).
It targets the **older** `main` commit `116241a`; do NOT reapply it over
the merged PR #1733, because doing so would overwrite the independent
approval gates and the corrected 945-prestart-quote replay. Only the new
`TBT_TOP_REQUIRE_MARKET_SIDE` option is carried forward.

- **Default OFF, independent approval:** the existing workflow emits
  `TBT_TOP_REQUIRE_MARKET_SIDE=true` only when
  `vars.TBT_TOP_REQUIRE_MARKET_SIDE_OWNER_APPROVED == 'true'` **and**
  the owner-supplied value `TBT_TOP_REQUIRE_MARKET_SIDE` is `1` or `true`.
  Merge alone cannot enable it.
- **Behavior when explicitly approved:** TOP rejects a picked side if
  `betting.fair_implied_probability < 0.5`, provided the fair value is
  finite, in (0,1), and `betting.captured_at < scheduled_at` with
  timezone-aware timestamps. A missing, invalid, or post-start price
  causes no side veto. TOP rejection audit counts
  `market_favours_opponent`. Existing VALUE and PRIME selection
  logic, TOP price floor and public model probability remain unchanged.
  A candidate vetoed for market disagreement cannot re-enter through
  emergency TOP fill, even if both optional features are enabled.
- **Corrected trade-off (independently computed on the supplied 2026-11-20
  issued-results CSV):** among 1,140 settled Match Winner event IDs,
  945 have valid pre-start fair (195 fallback). TOP-like eligibility
  p >= .60 and odds >= 1.50 spans 43 observed days. Rank-only selects
  **73/121 (60.3%)**, whereas the veto selects **69/116 (59.5%)**.
  Shortfall days with fewer than 3 TOP-like picks rise **6 -> 10**.
  The supplied ZIP's **6 -> 8** figure used the stale 649-prestart-price
  parsing and does not reproduce under the corrected 945-price parsing.
  The 116-vs-121 denominator changes, so these rates cannot establish
  causal superiority or non-inferiority. It conflicts with the user's
  no-silence objective. Keep this veto **disabled**; this PR is not
  permission to activate it.
- **Evidence distinction:** the reported 7,635 ATP historical full-slate
  selections (2016–2026) and 139 BlinQ TOP picks are *different cohorts*,
  not an interchangeable head-to-head experiment. The supplied claims
  about their hit rates, significance and VALUE market ceiling have not
  been independently reproduced in this patch. Even the corrected
  replay uses issued-only, same-period selected picks and is exploratory.
  Do not represent any estimated improvement as validated prospective edge.

**Verification:** use the exact-head GitHub Actions backend/CI tests and
`tests/test_market_anchored_rank.py`. Check that setting all new flags
OFF yields unchanged selector outputs. No provider requests, CDB writes,
champion fitting, price-threshold changes or live refresh are part of
this small optional-feature PR.
