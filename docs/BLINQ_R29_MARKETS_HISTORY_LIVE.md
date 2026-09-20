# BlinQ 7.3.6-r29 — markets, history, LIVE radar and loader

## Base

This patch is built from the uploaded `7.3.6-r28` repository and keeps the
verified v7.2.8 Sets/Games history rules (structured score identity, BO3/BO5
verification and fail-closed handling).

## What was wrong and what r29 changes

### Double Faults

The old Aces/DF confidence calculation used the standard error of the historical
mean (`variance / sample_count`) as if it were the uncertainty of the next
match. With deeper history this approaches zero, so volatile Double Fault counts
could be shown at 90–97% confidence even though the next-match count is still
noisy.

r29 uses future-count predictive variance instead, with a Poisson-like variance
floor. Aces are capped at 93% and Double Faults at 88%. The UI/API also separate
`aces` from `double_faults`: Double Faults have their own Daily Hub tab,
entitlements, Results category and publication identity. A Double Fault card can
no longer appear in the Aces tab merely because both use the physical
`ace_picks` feed field.

Important: the repository does not contain the production historical parquet or
the exact failed cards from production, so r29 fixes the demonstrably incorrect
confidence/selection behavior but does not claim a measured future hit rate.
Production settlement should be used to calibrate the next DF version.

### Why Aces could disappear

Aces and Double Faults were previously combined into one adaptive-fill pool.
High-confidence DF candidates could satisfy the target before the floor relaxed
enough for Aces. r29 fills Aces and Double Faults independently and reports
candidate/selected counts per market.

If `candidate_cards.aces == 0` after deployment, this is no longer a UI/fill
problem: the current-board players do not have enough valid stored Ace
statistics (minimum sample/evidence rules are intentionally fail-closed).

### Why Sets/Games could disappear

The repository already contains the v7.2.8 SG rebuild hardening. r29 fixes one
remaining selection starvation issue: Sets and Games are now adaptive-filled
independently rather than sharing one target. Existing structured-score and
best-of evidence rules are retained.

If either `candidate_cards.sets` or `candidate_cards.games` is zero, inspect the
SG dry-run diagnostics. Zero candidates means history/format coverage is still
missing for the current board; it should not be solved by bypassing the evidence
guards.

### LIVE Radar

The radar prefilter used defaults (`78%`, max odds `1.35`) that were materially
stricter than the Short Odds/PRIME pool, so it could have no eligible source rows
before any live-provider request. r29 aligns defaults to `68%` and max odds
`1.49` and exposes `eligible_prime_pool` plus rejection/skip diagnostics.

The autonomous worker still requires production configuration. The API and
GitHub Actions worker must share the same `BLINQ_LIVE_WORKER_TOKEN`; GitHub
variable `TBT_LIVE_RADAR_ENABLED` must be `true`. The workflow scans six times
roughly 50 seconds apart every five minutes.

### History / marketing KPI

The old public-history reset could leave the headline model KPI based on a tiny
sample such as 22 matches. r29 removes the arbitrary date reset and keeps all
settled rows that have genuine publication evidence. Older row-level published
Match Winner predictions are exposed as `model_only` Results publications; no
historical odds or ROI are invented for them.

Rolling model performance is calculated for 3, 7, 10, 14 and 30 days. The
headline card shows the highest accuracy only among windows with at least 30
settled Match Winner predictions. If no window reaches 30, it uses the largest
available sample instead of cherry-picking a tiny perfect streak. All windows,
sample sizes and normal Results filters remain available to the user.

### Loader

The supplied animated BlinQ SVG is integrated as
`web/assets/blinq_loading_r29.svg`. Its embedded raster was optimized so the
asset is about 186 KB rather than ~1.7 MB. The boot screen uses a dark emerald /
navy ambient background with a subtle court/grid aura, responsive sizing and a
reduced-motion fallback.

## Production sequence after deploy

1. Deploy r29 first so generated feeds use the corrected publication and
   selection contracts.
2. Run **Ace statistics** (`ace-statistics`). Recommended first pass:
   `max_requests=3000`, `ace_target_samples=18`, `ace_lookback_days=550`.
   Do not run another history writer at the same time. Then run `refresh`.
3. Inspect `ace_projection_report` in the generated feed/report. Check
   `candidate_cards`, `aces_selected`, `double_faults_selected`, adaptive floors
   and history match counts. If Aces candidates are zero, the fix is additional
   valid Ace statistics for current-board players, not a frontend change.
4. Run **SG rebuild** (`sg-rebuild`) with `max_requests=2000`,
   `sg_target_samples=24`, `sg_lookback_days=730`. Inspect
   `.cache/tbt/sg-history/sg_run_summary.json` and
   `sg_projection_dry_run.json`, then run `refresh`.
5. Configure LIVE Radar: Azure Production App Setting
   `BLINQ_LIVE_WORKER_TOKEN`; matching GitHub Actions secret
   `BLINQ_LIVE_WORKER_TOKEN`; GitHub variable `TBT_LIVE_RADAR_ENABLED=true`;
   optionally `BLINQ_PUBLIC_BASE_URL`. The admin radar diagnostics now show
   PRIME eligible/total, live events, candidates/signals and provider skip
   reason.
6. After several settled days, compare DF `hit/miss` Results by 3/7/10/14/30
   days before adjusting the DF model again. Do not infer calibration from the
   displayed confidence alone.

## Local validation

- Focused r29/market/admin/history/LIVE suite: **55 passed**.
- Updated cumulative UI/release regression contracts: **47 passed**.
- Broad locally runnable suite (Azure smoke excluded): **569 passed, 1 skipped**;
  the remaining **8 failures** require local `pyarrow` for parquet tests.
- Azure API smoke collection additionally requires `azure-functions`, which is
  not installed in this execution environment.
- Python compilation and `node --check web/app.js`: passed.
