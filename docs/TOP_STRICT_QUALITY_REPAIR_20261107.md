# BlinQ TOP selection quality repair — 2026-11-07

## Objective and approval
Restore predictable TOP (match-winner) selection after poor public Results.
Do not optimize a simulated training holdout in place of the actual eligible
pre-match offer; compare ALL frozen selected and unselected candidates before
any publication policy is promoted.

## Immutable product decisions
- TOP: winner market, decimal odds >=1.50, no upper odds cap.
- VALUE keeps exclusive priority: decimal odds >=1.80 **and** symmetric
  two-way odds gap <=15%, provided existing probability and quality gates pass.
  Thus a winner with odds >1.80 and gap >15% may still qualify for TOP.
- Only TOP's daily quality relaxation is removed; 80% is a provisional,
  previously existing **BlinQ-adjusted** confidence floor, not a claim of
  verified 80% hit rate. No minimum daily TOP count, no invented tip quota.
- ACES, DOUBLE FAULTS, existing local random ACES odds 1.6–1.8,
  PRIME, CDB, champion model and archive grades are untouched.
- ATP/WTA-first is the research direction. ITF, Challenger and WTA125 are
  separate cohorts; no fabricated main-tour assignment and no new arbitrary
  ITF eligibility threshold. A tour-only ATP/WTA filter is unsafe because the
  same broad `tour` field can contain ITF/Challenger events.

## Implemented in draft PR
- `api/tbt/services/market_selection.py`: candidate TOP selection cannot
  relax below 80% or fill a count; existing VALUE priority is preserved.
- `web/ui-config.json`: visible policy metadata reflects zero required TOP
  picks and fixed 80% floor.
- `build_selection_candidate_snapshot`: stores the original pre-match
  `competition` plus `selector_snapshot_at`. This is the date of the
  selection snapshot **not** a proven model inference timestamp.
- `scripts/replay_top_strategy.py`: read-only replay from frozen full-slate
  monthly candidate snapshots + canonical CDB completed matches. Separates
  original frozen candidate TOP, strict-80 across all tours, strict-80 on
  independently known pre-match ATP/WTA main circuits. Records actual quotes
  only if independently timed >=15 minutes pre-start; requires exact event,
  both player IDs, tour and schedule join. Reports 1u hypothetical ROI and
  W/L without treating pending/ambiguous cases as losses or actual publications.
- Tests cover VALUE at the 1.80 boundary, odds >1.80 outside the VALUE gap,
  no quota, zero TOP, >=1.50 boundary, evidence quality, no accidental
  mixing of post-match tournament level into pre-match selection, late prices,
  identity mismatches and original results contract.

## Replay command
With already downloaded, SHA-verified private release assets (NO paid provider
calls and NO CDB write):

```sh
python scripts/replay_top_strategy.py \
  --snapshots PATH/selection_candidates_2026-10.json.gz PATH/selection_candidates_2026-11.json.gz \
  --canonical PATH/history-2026.parquet \
  --out PATH/top_strategy_replay.json
```

Compare on the same dates with untouched original public issued receipts;
a frozen candidate assignment **does not establish that a bet was issued**.
Use a chronological development/validation split, predeclared policy and later
forward cohort. For every category x odds band x confidence x depth segment,
show N, wins, losses, void/pending, hit rate, ROI, actual vs expected and
confidence intervals. The required outcome is improved reliably verified TOP,
not maximum count nor selection of the best looking past slice.

## Acceptance / no-deploy gates
1. Targeted + full regression CI passes, plus independent source readback.
2. Original and revised selector compared on same full pre-start quoted slate;
   missing odds, post-start quotes, ambiguous identity and unproven category
   cannot count as wins or allowed top-tier category.
3. Report separately ATP/WTA main, Challenger, WTA125, ITF M15/M25/W15/W35/
   W50 etc. Date split fixed before threshold choice, later holdout blind.
4. Confirm exact VALUE and ACES production behavior unchanged.
5. Owner reviews observed outcome and tradeoff (coverage vs success and ROI);
   only then merge/deploy and independently read back production.

## Status / evidence
GitHub draft PR #1452:
https://github.com/BackstageTalks/tbt/pull/1452

Implemented on an isolated branch; **NOT MERGED / NOT DEPLOYED**.
No independently verified improvement in live hit rate or ROI is claimed.
Current session cannot read the complete private frozen monthly release
assets or the user's prior Codex local workspace; their absence is a release
gate, not permission to replace history with training scores. No CDB mutation
or paid provider calls were performed.

## Next action
Finish CI; run the private full-slate, exact-settlement, pre-match historical
replay on the untouched frozen assets; record tested sample sizes, candidate
counts and rejection reasons; review outcome before any public selector swap.
