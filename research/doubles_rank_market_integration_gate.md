# Doubles ranking and handicap/totals integration gate (research-only)

This file is an implementation gate, **not** approval to change production predictions.

## Inputs and provenance
- WTA doubles ranking: `BackstageTalks/tbt-data` release `blinq-kaggle-research-integration-2026-10-07`, asset `wta-rankings-doubles.jsonl.gz`. Require manifest SHA-256 verification, explicit Apache-2.0 source license and verified player crosswalk.
- Alimoh89 market: `BackstageTalks/tbt-data/research/historical_market/alimoh89_2014_2025/manifest.json`. Verify every sidecar SHA-256; preserve existing 20,342 canonical moneyline enrichments and do not reimport.
- Source authorization for Alimoh89 is operator-confirmed for noncommercial BlinQ use; do not generalize that authorization to other datasets.

## Fail-closed eligibility
1. Resolve both doubles members to unique stable player IDs; reject name-only joins, duplicate rank keys, ambiguous crosswalks, and conflicts.
2. Use only ranking observations whose **publication/availability** time is strictly earlier than the match prediction cutoff. A ranking date alone does not prove publication time.
3. Deduplicate older WTA supplement versus historical ranking on (player ID, ranking week, ranking type); reject conflicting values and report overlap.
4. Market handicap and total **lines** need independently supported timestamp before the prediction cutoff. A source field named opening_price does not establish the line's availability.
5. Keep recorded-final prices, match outcomes and post-start observations outside prediction features. Research-only labels/closing validation may use them after temporal separation.
6. Compare baseline DOUBLES-ELO-v1 to an experimental ranking-aware variant in a chronological, purged walk-forward evaluation, reporting sample size, coverage, accuracy, Brier, log loss, calibration, and odds-aware ROI only where legitimate pre-match prices exist.
7. Require meaningful improvement and no material subgroup regression before proposing any promotion. No automatic model promotion.

## Acceptance evidence
- Immutable source SHA-256s and rights evidence.
- Identity match/reject counts and overlap/dedup report.
- Timestamp availability coverage and quarantined counts.
- Baseline-versus-candidate reproducible walk-forward report.
- Zero production writes and zero production-model changes in this research gate.
