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

## Independent readback of real issued TOP and VALUE (2026-11-07)

Evidence run: https://github.com/BackstageTalks/tbt/actions/runs/42420587006
Research artifact \`issued-top-categories.json\` is derived from exact published
\`ledger.json\` commitments and an independent canonical CDB outcomes readback.
The audit neither reads an advertised public Results count as truth nor
conflates candidate records with issued wagers.

- 459 issued TOP/VALUE publication rows discovered; 389 unique confidently
  matched to canonical completed outcomes with a pre-start timestamped quote,
  217 wins / 172 losses; combined ROI -5.83% flat 1u.
- Actual TOP: **272 completed / 152 wins / 120 losses / 55.88% hit / -29.21u
  / -10.74% ROI**.
- Actual VALUE: **117 completed / 65 wins / 52 losses / 55.56% hit / +6.54u
  / +5.59% ROI**. It is critical to evaluate sections separately.
- Historical TOP Challenger: 42/83 (50.60%), -21.86% ROI.
- Historical TOP WTA125: 12/27 (44.44%), -31.25% ROI.
- Historical TOP ITF W50: 13/17 (76.47%), +19.90% ROI; very small sample.
- Historical TOP ITF W35: 8/15 (53.33%), -7.57% ROI.
- Historical TOP ITF M15: 14/22 (63.64%), -1.57% ROI.
- Historical TOP ITF M25: 19/28 (67.86%), +13.13% ROI.
- Level UNKNOWN: 48 actual TOP; **never** silently reclassify these
  as proven ATP/WTA main tour using merely a generic ATP/WTA \`tour\` field.
- The audited ledger's latest independently scored issued date was 2026-11-04;
  it DOES NOT include every member Results settlement dated Nov 6 and 7.
  Hence this is not the up-to-the-minute website performance figure.
- 10 raw duplicate-price conflicts quarantined; 8 unmatched canonical events;
  34 void or unresolved issued items skipped; 3 after cutoff; 19 never issued;
  these rejection counts are nonexclusive and have different denominators.
- The report preserves split by category, publication section, exact model
  version and issued date. Later CI revisions add model/section/category
  interaction and stable conflict-key quarantine.

## Decision following independent results

**DO NOT DEPLOY** the experimental fixed-80 live selector as a successful
quality fix: its frozen historical 7.2.1 selection had 6 wins / 7 losses,
while original cohort had 16 wins / 17 losses on a different denominator.
No paired out-of-time improvement has been proven.

Main ATP/WTA-first remains a user-directed focus, not a proven eligibility
policy or source of invented extra tips. Frozen 2026 snapshots have incomplete
pre-match tournament-level evidence; new snapshots now retain it.
The last missing work before any safe rollout is (1) reconcile the current
web Results and latest issued source with recent (Nov 5-7) settlements,
(2) historically match the full same-day priced slate and independent outcomes,
(3) evaluate main-tour-vs-other policies on unseen later dates rather than
outcome-picked conditions. Keep ACES, VALUE and champion unchanged.

Current PR status: DRAFT ONLY, NOT MERGED, NOT DEPLOYED.
