# BlinQ 7.2.1 — winner reliability and selector replay (2026-11-03)

**State:** PREPARED. This record is not proof that a replay ran.

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

**PREPARED:** isolated branch analysis/selection-reliability-replay-20261103 with read-only script, regression tests and workflow. Actual CI replay, per-fixture canonical outcomes and active serving model SHA must be independently verified before reporting A/B as answered. Revisit only failed technical assumptions, never bypass provenance or identity guardrails.

**Acceptance:** regression tests, verified immutable readback, chronological model-isolated A/B report with coverage and diagnostics, independent confidence/calibration review, then separate forward shadow. Champion and current published selector stay unchanged until explicit owner decision.
