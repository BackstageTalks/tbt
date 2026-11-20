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
