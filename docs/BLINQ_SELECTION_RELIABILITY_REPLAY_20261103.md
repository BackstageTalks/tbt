# BlinQ 7.2.1 — winner reliability and selector replay (2026-11-03)

**State:** IMPLEMENTED + 20/20 TESTED + DATA READBACK VERIFIED, forward cohort awaiting new real observations. No model/selector deployment.

## Goal and authorized scope

A — for each exact frozen model version, measure pre-match winner prediction quality on all unambiguous, canonically settled candidate matches: accuracy, Brier, log-loss, ECE, sample sizes, coverage and tour/surface/level/confidence/data-depth segments.

B — replay the frozen TOP/VALUE/PRIME candidate assignment versus predeclared confidence-first and quality-first ordering on the same historically priced candidate universe and exact original section/day capacity. Validate selection using held-out, correctly timed match outcomes, never training labels as inputs.

Investigate five original points: (1) data/serve-return quality, (2) ATP/WTA, tournament and surface reliability, (3) 65–80% confidence/calibration, (4) TOP/VALUE/PRIME allocation, (5) rank values and freshness after 2026-10-06.

**Binding limits:** Do not retry EV/ROI/CLV optimization. No CDB write, provider call, training, public publication, serving champion change, or automatic selector deployment. Preserve active rules, preexisting work and approvals. Forward shadow and later release need independent evidence and owner decision.

## Pinned discovery evidence (not runtime performance)

- App baseline: BackstageTalks/tbt commit 534412d18d7af868fb08d4f3de981fb5d094af66 (2026-11-03T19:43:37Z).
- Existing snapshot instrumentation merged in [PR #456](https://github.com/BackstageTalks/tbt/pull/456). Includes selected and unselected singles, models and confidence, two-way odds if captured, rank **values** and sample depth, but excludes outcomes.
- Private release tbt-predictions-v1 ID 383532078: selection_candidates_2026-10.json.gz (asset ID 694581598, 1,225,365 bytes) and selection_candidates_2026-11.json.gz (asset ID 704387727, 219,369 bytes) observed 2026-11-03.
- Canonical release tbt-data-v1: history-2026.parquet (27,021,388 bytes), authoritative history manifest and bundle manifest, observed 2026-11-03.
- audit/market-quality-latest.json ends on 2026-10-04; not a measurement of current 7.2.1.
- Model-quality [issue #965](https://github.com/BackstageTalks/tbt/issues/965) and Stage 3 deployment [issue #959](https://github.com/BackstageTalks/tbt/issues/959) remain open.

## Fail-closed replay protocol

1. Pin release asset IDs, byte sizes and timestamps before/after; verify hashes of downloaded inputs against committed manifests when present; canonical year SHA must equal history manifest.
2. Load October/November gzip candidate snapshots; reject malformed schema and post-match/outcome fields.
3. Fix one sample anchor per Bratislava betting day: earliest generation at/after 06:00 local. Avoid repeated within-day counting and model/event duplicates.
4. Require exact canonical match ID and pair of player IDs, pre-match schedule >=15 minutes after prediction time, valid probabilities and genuine final result. Report missing/ambiguous/void matches separately; never infer their result.
5. Keep model versions separate. A: raw and displayed probability accuracy, Brier, log-loss, ECE, confidence, tour, level, surface, depth and rank-value availability.
6. B: require source quote captured before sample and >=15 minutes before event, reproduce original eligibility floors. Baseline candidate assignment is NOT issuance; compare two selection orders with exactly the same original capacity by model, day and section; no EV optimization or outcome-informed candidate sorting.
7. Both serve/return denominator presence and rank timestamps are **NOT IN SNAPSHOT SCHEMA**, so this replay alone cannot establish their quality/freshness. Distinguish that gap in every summary. No automatic green conclusion on small/confounded cohorts.
8. Save only aggregate private report as a CI artifact. No public raw candidate rows.

## Progress and gates

**IMPLEMENTED / TESTED:** isolated research branch plus read-only workflow and corrected CDB rate-field mapping. Latest 20-case regression suite and verified readback passed (run 41715586327). Accuracy is available for *matched completed candidates*; the current serving model artifact SHA and true published-issuance outcomes remain separate unverified questions.

**Acceptance:** regression tests, verified immutable readback, chronological model-isolated A/B report with coverage and diagnostics, independent confidence/calibration review, then separate forward shadow. Champion and current published selector stay unchanged until explicit owner decision.


## Verified research checkpoint — 2026-11-03

- [Replay run 41709826091, attempt 2](https://github.com/BackstageTalks/tbt/actions/runs/41709826091): **SUCCESS** on code commit aa33a5e9fa9615aec742c46fb3117bfecb083687, 15/15 replay safety regression tests passed.
- Input SHA-256 and release asset ID/size/timestamp checked before/after; October and November prediction assets and canonical 2026 history verified against their committed bundle manifests. See the private aggregate job artifact for exact evidence.
- 24 daily anchors, 6,689 unique version/event candidates, two strictly separate versions. Current 7.2.1 candidate model has 1,762 unambiguously settled observations out of 2,384 candidates. Some candidates remain unresolved and are NOT scored.
- Initial event-to-canonical join returned zero because predictions carry native provider IDs; corrected using the existing source-native provider ID fields and exact player/tour/date gates. No names-only identity matching.
- Outcome evidence indicates raw-versus-displayed calibration mismatch worth independent forward validation; the selector comparison remains NOT READY for deployment: too few completely observed, same-capacity days, and most groups have missing outcomes. These are not public issuance metrics.
- Existing 2026 CDB post-match serve/return, break point rate and ranking-value coverage was counted; it is explicitly NOT proof of historical point-in-time serving features. October/November ranking freshness and true serve/return feature availability remain separate audit gaps.
- First attempt of run 41709826091 failed closed because canonical history-2026 asset was rotated during the read. New asset ID/byte count was independently observed; a single retry (attempt 2) completed with consistent input manifests.
- **Decision gate:** NO selector policy change, NO model promotion, NO CDB write, NO provider calls, NO production deploy. Await separate owner review and, if indicated, forward shadow with exact issued/captured/settled observations.

### Still open

1. Determine whether stale or missing canonical ranking values actually reach the serving model features; snapshot records values but not rank as-of times.
2. Inspect why feature-builder-compatible break-point rates have almost no confirmed paired evidence despite serve/return percentage coverage, without interpreting unrelated count fields as rates.
3. Validate the candidate cohort's unresolved outcomes and publication-versus-candidate differences to avoid outcome selection bias.
4. Forward shadow under same-event and pre-start evidence; do not auto-adjust arbitrary probability thresholds based on this retrospective replay.
5. Confirm currently serving model artifact SHA independently from live inference before making production-specific promotion statements.

## Final research integrity corrections (2026-11-03, follow-up)

- [CI run 41715586327](https://github.com/BackstageTalks/tbt/actions/runs/41715586327) is **successful** at commit 80aa72b9058c39bf0e3dc375fb2d764accc81d2f: **20/20 tests pass**, 24 historical anchors, 6,689 candidate-model/event rows, and verified private historical release readback. [Private aggregate report artifact](https://github.com/BackstageTalks/tbt/actions/runs/41715586327) contains both historical and frozen prospective JSON.
- Fixed replay's canonical settlement check to accept only genuinely final statuses with validated winner; provisional matches are excluded. Added paired betting-day identity verification so comparisons cannot pair different calendar days silently.
- Fixed the historical data audit's break-point rate field names to match the canonical feature-builder convention: `p1/p2_break_point_serve_win` and `p1/p2_break_point_return_win`; **count fields are never accepted as rates**. The earlier zero-coverage finding was a *measurement bug*, not a finding about missing source data.
- **Corrected current canonical CDB 2026:** 101,628 completed; 72,833 both service/return rates (71.67%); 10,160 both break-point rates (10.00%); 18,623 both ranking values (18.32%). October: 8,446 both service/return, 1,432 both break-point, 255 both ranks of 10,796 completed. November: 367 both service/return, 207 both break-point, **zero both ranks** of 984 completed. None of these post-match CDB figures prove the point-in-time availability in serving model's private rank-history features.
- Recovered prospective split is **predeclared 2026-11-04 Europe/Bratislava**. Read-only `forward-report.json` is independently reported from historical `report.json`. As of the verified run: **0 prospective days / 0 prospective candidates**, status `AWAITING_FUTURE_SNAPSHOT`; never interpret empty data as an automatic improvement.
- Research CI workflow is configured for a daily 11:17 UTC read-only schedule **after the research code is on GitHub's default branch**; it reads existing monthly immutable private snapshots and canonical history using pre/post asset verification. It makes **0 extra Tennis provider calls** and **0 CDB/feed/model writes**.
- Model 7.2.1 historical 1,762/2,384 matched completed candidate outcomes remain 68.90% accurate, raw Brier 0.1971. TOP forward quality-first improvement **is not established**: retrospective paired comparison has only five complete TOP days (16 examples).
- **Release gate stays closed:** no calibration change, selector reordering, champion swap or live service deployment. A separate prospective comparison on sufficiently many fully evaluated matching daily selections, a true issued/settled ledger, and active serving model SHA readback are still necessary before any production policy change.

### Acceptance and stop/go

Research-only infrastructure can be merged after green CI without touching production selection or the canonical writer. That is *not* authorization to activate a changed policy. No automatic promotion when sample sizes are small, status is unsettled, inputs are stale, or provenance is absent. Keep collecting frozen observations and report the actual denominator, missingness and per-version evidence before an owner decision.
