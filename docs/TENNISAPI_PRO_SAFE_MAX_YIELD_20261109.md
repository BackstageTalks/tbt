# BlinQ Tennis API PRO — maximum usable data per billed request, CDB-first

Checkpoint: 2026-11-09. Scope: ATP/WTA 2016–2026 provider-native data
collection and safe historical enrichment. **CDB remains authoritative.**
Existing provider-native importer and global single-writer/CAS lock remain
the only write path. No model, champion, external cron, quota or CDB
schema change authorized by this checkpoint.

## Measured baselines (not hypothetical future yields)

- Tennis API PRO daily `/api/tennis/events/odds/{day}/{month}/{year}`:
  **994 source event keys in a single paid request** (336 for the older
  historical cohort); 2 price-shaped choices per event, but **no verified
  bookmaker/market source time**. These are not 994 billable requests or
  994 safely usable CDB odds rows.
- ATP 2024 targeted native stats: 500 paid attempts, 2,787 independently
  persisted mixed canonical cells, 306 enriched matches and 194 rejected
  conflicts; 5.574 verified cells/paid request. No new fully quality-ready
  serve/return rows. The earlier 100-call pilot added 779 canonical cells.
- WTA 2023: 400 paid attempts, 3,179 persisted mixed statistic cells;
  7.9475 values/paid request. Cohort yields are not guaranteed transferable.
- Historical tournament date/round samples: 32 source rows/request;
  tournament last page: 30; player/team monthly aliases return identical
  payload digests in both tested cohorts (do not pay twice for aliases).
- Current private CDB conflict audit: 611 persistent native conflict
  markers, 1,696 existing NULL BP cells among them; no evidence yet that
  those NULLs correspond to safe provider values. Separate SHA-pinned
  CDB complement write **completed 2026-11-09** in
  [run #42580292332](https://github.com/BackstageTalks/tbt/actions/runs/42580292332):
  **4,178 persisted new NULL-only service/return values across 1,056 matches**,
  1,006,232 canonical matches retained, 0 overwritten original values,
  0 unverified identities; private reread verified the published release.
  The 1,685 contradictory rate matches remain quarantined.

## Priority register / evidence gates

| Priority | Task | Status / accept criteria |
| --- | --- | --- |
| P0 | Protect CDB while optimizing yield | Existing global lock, shared CAS budget, provider reserve, identity, dedup, evidence precedence, NULL-only, dry-run, native import, read-back and rollback preserved; no second writer |
| P1 | Consume **every event** in one 700–1,000-entry daily bulk odds response | **IMPLEMENTED read-only stage** in `tennisapi_bulk.py`, integrated into already-paid research probe; exact source key, per-event pair parse, provider-scoped dedup, quarantine, 100% event accounting. 994-event synthetic stress fixture; report aggregate-only. No CDB prices authorized |
| P1 | Verify raw odds market/provider/clock with live source evidence | **OPEN:** collect exact requested endpoint, provider-native market ID, choice orientation, quote/as-of timestamp and record clock semantics. Explicitly validate pre-start time for CLV. Until then, no bulk odds substitution for individual event odds, model or public prices |
| P1 | Maximize match-level serve/return/BP from each cached `getMatchStatistics` | **PARTIAL:** existing aliases and safe BP conversion are live. Next split per-field persisted NULL deltas, compare `servicePointsScored`, `receiverPointsScored` with denominators, preserve contradictory ALL vs set evidence, and never replace higher-quality CDB values |
| P1 | Reduce conflict losses without weakening identity | **PARTIAL:** existing full-response quarantine + per-field histogram; strict immutable non-NULL parser in merged PR #1493. Any per-field null recovery needs own evidence/quality precedence and native import readback; 194 ATP rejected calls are not retroactively recovered |
| P2 | Reconstruct verified PBP data | **RESEARCH:** 18-game fixture replays 110 points, 1/3 vs 4/5 break points; other events, original URL/event witness, missing terminal shot types and ties must be checked before any point-derived canonical stats |
| P2 | Surface-specific player/year profiles | **RESEARCH:** 63-match sample validates conservation; only finished seasons and verified player/year provenance; never use a full season for an earlier match in that same season |
| P2 | Tournament/day/round/season and player-month discovery | **PARTIAL:** existing category/day collector is native and cached. Compare incremental unique identities/net-new CDB values per paid call and request/page before substituting a route. Never confuse 32 observed rows with 32 validated matches |
| P1 | Multi-route request planner and accounting | **OPEN:** prioritize verified value per paid attempt, count retries and other consumers in shared 15,000/day and 6/s budget with 500 reserve, evaluate actual day remaining from ledger, keep 17:07–17:10 UTC reset pause, no fixed 90/25/75 or 750 limits |
| P0 | Import/production quality proof | **OPEN** for bulk-derived data: audit→quality→provenance→schema→dedup→identity→leakage→dry-run→native import→independent CDB read-back→integrity. Report raw / linked / net-new / enriched / conflicts / quarantined / truly persisted values |

## Current execution boundary

This change **does not** request provider calls or perform CDB writes.
The new `normalize_daily_bulk_odds` consumes the entire already-fetched
native map and returns PRIVATE normalized candidates alongside a public
aggregate-only report. Even a fully parseable two-sided entry is marked
`eligible_for_cdb_import=False` and
`eligible_to_replace_individual_market_fetch=False` until original
market/provider/quote-time evidence and canonical ID provenance are verified.
Unknown event IDs, duplicate/conflicting selections, unsupported markets,
malformed nodes and unknown live/suspension flags are quarantined, not
guessed or silently dropped. No raw event ID or price enters the research
artifact. The route remains on the existing globally guarded API client.

Required verification: new 994-entry stress test; malformed/duplicate/
suspended/clock cases; existing probe regressions; repository full CI; PR
readback; only then merge. To operationalize real bulk odds use, capture
a fresh **bounded** provider response (or reuse a correctly tagged cached
response) and measure the actual parseable two-sided/identity/time-valid
distribution. Do not claim 994 valid odds or historical prices before
that observation. The existing independent CDB writer should finish its
current locked operation without interference.

Evidence:
- https://github.com/BackstageTalks/tbt/actions/runs/42465293411
- https://github.com/BackstageTalks/tbt/actions/runs/42465442647
- https://github.com/BackstageTalks/tbt/actions/runs/42468614163
- https://github.com/BackstageTalks/tbt/blob/main/docs/TENNISAPI_PRO_MULTIROUTE_LIVE_QA_2026-11-07.md

## 2026-11-09: process the entire already-paid statistics response

- **Implemented on unmerged PR #1504**, baseline main
  `f8ce18db223a09101f4108af5b7725a10b35e4d2`; do not call this
  merged/deployed until exact-head CI and merge are verified.
- The checked-in authentic ALL-period statistics sample has complementary
  `servicePointsScored` + `receiverPointsScored` counts and a
  `pointsTotal` witness. These were previously inventoried but did not
  become serve/return cells. The new parser can derive up to 4 rates plus
  4 denominators **from one existing statistics payload**, with strict
  both-player closure, correct home/away orientation, no guessed denominator,
  no set-only mixing and no provider calls.
- Missing, malformed or internally contradictory count evidence produces
  no new inferred cells. Explicit direct-stat conflicts are rejected.
  The existing native importer still protects every non-NULL canonical cell
  and quarantines any entire conflicting response. Regression tests cover
  fixture conservation, inverted home/away, malformed evidence, direct
  disagreement, and actual enricher NULL-only/quarantine flow.
- **Unverified**: real future provider-response prevalence, per-response
  net-new CDB cell yield, additional 2016–2026 coverage and end-to-end
  performance. This PR does not replay historical raw cache or trigger
  paid API calls, CDB writing, model changes, production deployment or
  external-cron schedule changes.
- **Next**: exact-commit CI → review/merge → current-runtime processing
  readback → count real valid parsed rates and native CDB NULL-only persisted
  delta with the existing lock/CAS/audit path. Keep bulk odds research-only
  until real bookmaker/market/pre-start quote provenance is proven.
- **Evidence**: PR https://github.com/BackstageTalks/tbt/pull/1504;
  service-complement persisted readback:
  https://github.com/BackstageTalks/tbt/actions/runs/42580292332.
