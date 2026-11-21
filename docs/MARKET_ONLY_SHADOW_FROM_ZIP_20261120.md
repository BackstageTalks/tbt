# Market-only shadow experiment — 2026-11-20

## State and restrictions

**PREPARED / READ-ONLY research. No publication or model promotion.**
This branch and draft PR contain only an isolated research adapter, frozen
parameters, an offline full-slate staging interface, and evaluators.
The live champion, current TOP/Value selection, other betting markets, CDB,
external scheduler, API quota and PR #1727 frozen M4 research are unchanged.

No archive or backup is created by shadow-only checks; AGENTS.md controls.
Do not add a second writer or use post-match odds to fit pre-match predictions.

## Authorized source and data audit

Supplied ZIP SHA-256:
`b22b27af2693be969ca0b11d18e5dba55f3c978a0b70728116fd0b86ecf11f1f`.
Original results export SHA-256:
`2ef1fcd835b1381024f64475a21efcbf7d2102c32eb71998c480592f4c9e2eb4`.

Source ZIP did NOT include the claimed historical 45,903 ATP pre-match
Oddstrader observations or verified WTA history. Its end-of-day prices have no
proven captured_at before scheduled start. The supplied slope/intercept
(1.102, -0.009) are therefore NOT independently fitted or authorized for
live probabilities. They are frozen in `research/market_only_shadow/params_2026-11-20.json`.

## Reproduction, selected-only historical cohort

Command:

```bash
PYTHONPATH=api python scripts/reproduce_market_only_shadow_csv.py \
    --results /mnt/data/blinq_vysledky_2026-11-20.csv
```

- 1,140 unique settled match_winner picks; 945 with fair, 195 absent.
- All 945 have capturable pre-start issued prices when timestamps are parsed
  with `pd.to_datetime(..., format="mixed", utc=True)`. The uploaded reference
  scripts incorrectly report only 649 due to fixed ISO parser assumptions.
- 945 paired: original BlinQ 755/945, log loss .46774596;
  raw market 764/945, .43904648;
  market-only transform 760/945, .43196323.
- The new transform does NOT improve correct winner identification over market.
  Positive-slope market-only calibration preserves top-N order on the same
  candidate slate, while its intercept can flip near-50/50 winner choices.
- A1 market-alignment: 736/898 vs same-N market 736/898.
- A2 fair >= .75: 506/562 vs same-N market 506/562.
- A3 abs(model-fair) <= .10: 571/656 vs same-N market 582/656.
- A1+A2+A3: 451/499 vs same-N market 456/499.
The export only contains *issued* picks, not the full fixture slate. These
observations must not tune active TOP or VALUE selectors.

## Implemented research components

- `api/tbt/services/market_only_shadow_research.py`: independent A1/A2/A3
  selectors; strict price/selection ID/issue time; explicit original-p
  fallback, immutable incoming card; offline full-slate staging adapter and
  pure first-capture append helper (NOT a writer).
- `scripts/reproduce_market_only_shadow_csv.py`: historical
  selected-only check against equal-N market selection.
- `scripts/audit_market_only_shadow_readonly.py`: offline
  outcome-independent input validation, then (ONLY after 400 new valid settled,
  strictly pre-start paired-fair matches) matched model/market/shadow
  probability scoring and subgroup audits with bootstrap/McNemar.
- `tests/test_market_only_shadow_research.py`,
  `tests/test_audit_market_only_shadow_readonly.py`: synthetic no-leakage,
  immutable capture, competing identities, missing fair and 399/400 gate tests.

Run focused tests using:
```bash
PYTHONPATH=api:scripts python -m pytest -q \
  tests/test_market_only_shadow_research.py \
  tests/test_audit_market_only_shadow_readonly.py
```

## Outstanding gates

- B1 full-slate capture is a PURE STAGING INTERFACE ONLY. The current private
  `frozen_721_shadow_capture.py` already operates under the caller's
  coordinated crossrepo lock and checks persisted readback, but it does not
  certify complete two-way bookmaker pre-start quotes for every fixture.
  Do not add a parallel ledger writer or silently substitute issued TOP cards
  for whole-slate snapshots. No actual new full-slate cohort has been persisted.
- C1–C5 residual model fitting is BLOCKED: independent PIT verification
  of historical prices and CDB features is mandatory. No training or API
  request was made.
- The original PR #1727 remains an unmerged, independent M4 experiment.
- Any prospective decision requires >=400 genuinely new, settled and
  pre-start priced match pairs, separately assessed ATP/WTA, and an
  independent exact-same-N market benchmark. This code never auto-promotes.
- Production activation requires explicit owner permission.


## A0 no-silence daily shadow shortlist (2026-11-21 correction)

`select_daily_shadow_picks(cards, params, *, n_min=5)` is a PURE research
function. Groups by **UTC scheduled match day**, applies a stable
`(tier, -shadow_probability, event_id, selection_id)` order and returns
`min(slate size, max(n_min, count_T0))` per observed day.
Each returned card carries `selection_tier` and `selection_basis`, both
top-level and in `shadow_research`. Source cards and all public fields are
untouched; `shadow_eligible_for_actual_publication=False`.

- **T0:** market shares the model favorite, fair >= .75, abs(model-fair) <= .10.
- **T1:** valid pre-start two-way fair and same favorite, not T0.
- **T2:** valid pre-start two-way fair and different favorite.
- **T3:** missing/unverifiable fair; falls back to frozen original model-p.
- Tier ranking demotes old A1/A2/A3 vetoes instead of dropping candidates.
  With fewer than n_min unique events in a day, return all, but mark this
  as an A0 coverage shortfall rather than claiming the minimum was met.
- Duplicate canonical event IDs, including two opposite sides of one match,
  are fail-closed; daily selection cannot be inflated by duplication.

### ATP opener variant provenance

The source-claimed `opener_fallback` uses slope **1.088**, intercept
**-0.008**, claimed fit **36,972** ATP match_winner observations,
`BackstageTalks/tbt-data/data/oddstrader/atp`, opener column and de-vig
two-way odds. This is **not** an independently reproduced or timestamp-proven
pre-start fit in this PR. It can only be evaluated with explicit
`calibrate_market_only(fair, params, variant="opener")`, never silently.
The main 1.102/-0.009 variant remains unchanged.
**Neither main nor opener is certified for WTA.**

### B2: receipt-backed daily minimum before outcomes

`scripts/audit_market_only_shadow_readonly.py` now accepts optional
`--issued-shadow private_issued_receipts.json`. For >=400 post-freeze,
settled, exact-matched, pre-start two-way fair observations it derives A0
shortlists from the **whole provided pre-match slate**, not from settled
outcomes. It refuses to score when any observed UTC slate day has fewer
than 5 computed candidates; when issuance receipts are absent, incomplete,
duplicated, after-start, or fail to match (event_id, selection_id, tier,
basis, UTC day), it also refuses to score. Receipts are read-only JSON and
require `receipt_id` and `shadow_issued_at`; the helper **does not
write or fabricate receipts**.

An empty day **not present in the captured slate is not observable**;
full-slate source completeness and independent release read-back are still
mandatory external evidence before claiming the real system never goes
silent. This branch is not a real issuer or a new writer.

The frozen A0 minimum (5) and absence of WTA fit verification are
executable fail-closed guards in `load_shadow_params`.

### Focused local and exact-head testing

```bash
PYTHONPATH=api:scripts python -m pytest -q \
  tests/test_market_only_shadow_research.py \
  tests/test_audit_market_only_shadow_readonly.py
```

Verify the current PR HEAD and exact GitHub Actions run; do not report
previous green CI runs as proof for newly committed A0/B2 changes.


## B1 existing-writer capture hook — 2026-11-21

**IMPLEMENTED IN DRAFT PR, NOT A VERIFIED LIVE CAPTURE.** 
The guarded existing \`data.yml\` refresh/current-refresh pipeline now
invokes \`scripts/market_only_a0_private_capture.py\` AFTER existing
Tennis API Pro/PropLine market enrichment, under the same external scheduler,
\`tbt-production-deploy\` serialization and CDB global writer lock. There
is NO second cron, provider request, CDB importer, model fit, public
\`top_policy\` or \`market_selection\` mutation.

- Source: the **whole model-discovered same-UTC-day singles fixture slate**,
  not just the issued TOP/VALUE cards. Capture pre-start original model p,
  exact internal CDB match ID, provider event ID, exact players, tour,
  surface, model version and timestamp.
- Market: only actual primary-provider two-way, same-source H2H prices
  (\`match_winner_market.source_id_known=True\`), with both no-vig
  probabilities summing to one. Never silently replace missing fair with
  \`1/odds\` or make a fake bookmaker. A conservative real observation clock
  AFTER quote enrichment establishes strict pre-start evidence; the
  historical publication clock may be an intentionally projected 06:01
  selection time and is NOT a real quote capture stamp.
- Quote-missing model fixtures enter the immutable full-slate cohort with
  \`fair_* = null\`, T3 shadow fallback to original model probability.
  They do NOT count toward 400 priced paired B2 observations.
- First-capture snapshots and issued A0 \`selection_tier\`/\`selection_basis\`
  receipts are append-only by identity. Source/model-version changes
  and conflicting IDs fail closed. A first daily slate's issuance is
  immutable; later discovered events remain in the broader evaluation
  population with \`a0_first_daily_slate=false\` but cannot rewrite the
  already frozen issue.
- CDB settlement only by the exact canonical \`match_id\`, same players and
  scheduled start; ambiguous/postponed cases are not guessed from names.
- Persistence: only **existing** \`tbt-model-shadow-v1\` ReleaseStore writer,
  adding \`market_only_a0_shadow.json\` inside the same globally locked
  refresh. After checksum-manifest upload, a separate fresh ReleaseStore
  instance downloads and **byte-compares** the remote asset. No new
  backup or parallel writer.
- Full-slate status is relative to the provider-discovered available model
  predictions on that day. An unseen match or a day without a successful
  refresh cannot be declared covered; report this limitation.
- B2 accepts a verified read-only private release asset via
  \`--private-ledger market_only_a0_shadow.json\`, with 400 new valid
  settled pre-match paired matches and receipt-backed A0 daily minimum.
  It does not train, re-fit or auto-promote.
- **Activation boundary:** the PR is still draft and not merged. No live
  A0 receipt/read-back metrics yet. A successfully completed CI only
  verifies code/tests, not real daily capture. Do not claim the 400-match
  prospective evaluation has started without an actual persisted receipt.

Focused verification and scope:
\`\`\`bash
PYTHONPATH=api:scripts python -m pytest -q \
  tests/test_market_only_shadow_research.py \
  tests/test_audit_market_only_shadow_readonly.py \
  tests/test_market_only_a0_private_capture.py
\`\`\`
