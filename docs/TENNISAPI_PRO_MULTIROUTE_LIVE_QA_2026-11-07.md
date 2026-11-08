# TennisApi PRO — bounded multi-route live QA, 2026-11-07

## Goal and scope

Determine which documented \`tennisapi1.p.rapidapi.com\` routes actually return
usable data with the current RapidAPI PRO subscription, and whether one HTTP
response can yield multiple source-native matches or Match Winner odds.
**No canonical CDB writes, no model changes, no market promotion, no extra
unscheduled imports.**

Authoritative evidence is the run artifact from
\`.github/workflows/tennisapi-contract-live-probe.yml\` using
\`phase=bulk\`, a known source-native event witness, and the existing guarded
\`RapidTennisClient._get\` (shared CAS ledger, provider quota headers, 500
reserved calls, 6/sec global pacing, no retries). Maximum 16 provider calls
per run, including the witness. The implemented list currently schedules 15
calls in the happy path.

### Source-native source witness and route groups

Witness \`17449516\` was previously verified as a live
\`/api/tennis/event/{id}\` detail; the new run **must independently revalidate
the exact ID and source-native player pair, tournament, season and date**.

Source-context calls:
- \`/api/tennis/tournament/{tournament}/season/{season}/events/last/0\`
- \`/api/tennis/tournament/{tournament}/schedules/{day}/{month}/{year}\`
- \`/api/tennis/player/{playerId}/events/{month:02d}/{year}\`
- \`/api/tennis/team/{teamId}/events/{month:02d}/{year}\`
- \`/api/tennis/event/{eventId}/provider/1/winning-odds\`
- \`/api/tennis/event/{eventId}/odds\`
- \`/api/tennis/scheduled-tournaments/{day}/{month}/{year}/page/1\`
- \`/api/tennis/calendar/{month}/{year}\`
- \`/api/tennis/events/odds/{day}/{month}/{year}\`
- \`/api/tennis/tournament/{tournament}/season/{season}/rounds\`
- \`/api/tennis/tournament/{tournament}/season/{season}/cup-trees\`

Independent list calls:
- \`/api/tennis/events/odds/featured/1\`
- \`/api/event/newly-added\`

Documented AO 2023 *example only*:
- \`/api/tennis/tournament/2363/season/48186/events/round/32/slug/round-of-64\`

A HTTP 200, non-empty list, or overlapping event ID alone does **not** prove
match uniqueness across routes, ATP/WTA completeness, current account
entitlement for all seasons, point-in-time odds, CDB matching or net-new values.
HTTP 204 is **no data for the exact parameters**, not an inaccessible route.
HTTP 403, 404, 429 and malformed quota headers are reported distinctly.
Only aggregate structural counts and payload SHA-256 hashes leave the job;
full event/player/price payloads are never uploaded as artifacts.

## Operational status

No live probe is considered done until a workflow run actually executes,
provides per-route HTTP status and response shape, and passes the independent
run/artifact inspection. An authenticated GitHub Actions provider client is
required; searching public docs and green offline tests alone are insufficient.
The source report is research-only and cannot authorize import. CDB write
requests are explicitly disallowed in the workflow request JSON.

## Verification

\`\`\`bash
PYTHONPATH=api:scripts pytest -q \
  tests/test_tennisapi_bulk_contract_probe.py \
  tests/test_probe_tennisapi_extended_contract.py
\`\`\`

The trigger file \`.github/tennisapi-contract-probe-request.json\` is written
only after PR code and CI have been checked; that **main branch change** starts
the guarded live job. For independent readback inspect the exact run ID, job
logs, uploaded JSON, consumed paid requests and unchanged CDB state.

Product timing: provider reset is independently known as **17:09 UTC**, not a
guaranteed local 18:10 through DST. Keep the historical 17:07–17:10 UTC pause.

## Revised efficiency objective — 2026-11-07

User priority is **maximum verified, usable fields per billed request**, not
preparing an inventory of unmatched event IDs. The 11 unmatched IDs and 196
existing BP NULL cells from the earlier overlap audit are *not* proof that
additional individual paid calls will yield new usable data.

Confirmed historical observations (not promises for other dates/cohorts):

- Daily `/api/tennis/events/odds/{day}/{month}/{year}`: one response with 993
  event-key entries, of which 782 have source ID claims in the read-only CDB.
  No pre-match quote timestamp or replacement value is validated.
- Tournament/day or round sample: 32 source event rows per call; last page:
  30 source event rows; player-month: 7. These are **raw observations** and
  may overlap other responses.
- Ten-call historical bulk/CDB QA: 165 raw rows, 109 eligible unique source
  events, 98 exact CDB links, 46 repeated appearances across endpoints.
  **Zero new canonical CDB values** were written.
- BP-only controlled 200-call run 42407952959: **zero** persisted new BP
  values. Do not repeat broad low-yield pulls merely to spend quota.

Read-only follow-up in PR #1447 adds an aggregate shape profile for EACH
already fetched daily bulk odds map, using no additional API request. Before
substituting it for individual event odds requests, verify that map values
actually include unambiguous event/provider/market/selection data, support
all required fields, and that historical pre-match quote times are provable
where required. A timestamp-like field name alone proves none of these.

Future selection policy: compare net-new validated canonical cells per paid
call (including retries and failed calls), payload-field completeness and
cross-endpoint duplication. Prefer batch date/round/season routes only where
their marginal gain beats the existing category/day collector. Keep source
identity and quality gates; do not introduce a competing CDB writer, alter
the active model, weaken the shared quota reserve or silently switch
production acquisition routes. Current state: **measurement PR only**; no
production endpoint substitution has been executed or verified.

## Verified 500-request CDB enrichment experiment, 2026-11-07

Authorized provider-native statistics test, NULL-only canonical write, no model change:

| Run / cohort | Paid requests | Persisted new fields | Enriched matches | Conflicts | Empty |
| --- | ---: | ---: | ---: | ---: | ---: |
| Actions #42416694839, ATP/WTA 2023 | 100 | 95 | 11 | 73 | 16 |
| Actions #42417826366, WTA 2023 | 400 | 3179 | 400 | 0 | 0 |
| **Total** | **500** | **3274** | **411** | **73** | **16** |

Independent CDB read-back: first run 95 persisted values,
history-2023.parquet SHA-256 2a4ba516bca99e95138fa095f5a8ed0dd9f862ad6754266c71b3ff8e57d142ea.
Second run 3179 persisted values, current history-2023.parquet SHA-256
361d763d92881d16ef2d2602f7e9fa5559affd1843a072898bf24a862602a781.
The verified 500-request average was 6.548 new statistic cells/call;
the WTA-only 400-call sample achieved 7.9475 cells/call. Both reports
recorded zero new fully serve/return quality-ready rows. These counts
include all safe null-only whole-match fields, not solely break-point cells.
No demonstrated model accuracy improvement and no model activation.

PR #1446 introduced a count-backed provider breakPointsScored mapping under
existing identity/quality checks. Use the evidence-backed productive WTA 2023
cohort in adaptive prioritization, with dynamic re-evaluation of yield instead
of permanent allocation or starving other cohorts.

Separate read-only API response-shape QA: Actions #42417199888 and
#42418057862 spent 2 + 2 additional guarded provider requests, outside the
500 statistics calls. Each found 994 event-key entries in one daily bulk odds
response; every entry carried a choices member. Per-event usable prices,
selection orientation and historic pre-start timestamps remain unverified.
PRs #1447, #1450, #1451 measure structure only. No price import or
individual-event API replacement is authorized yet.

Remaining: validate provider-native choices row fields and point-in-time
semantics with a future bounded, approved observation; then measure actual
valid new prices per billed call. Preserve CDB single-writer, CAS quota,
provider reserve and NULL-only protections. No additional paid calls were
made for this documentation/read-back.

## Live cross-era revalidation, 2026-11-08

Operator authorized at most 300 paid requests **per test**, but the existing
research-only, quota/CAS-guarded bulk contract validated the requested routes
using **15 paid calls per cohort / 30 total**. Provider limit and 500-call
reserve remained enforced, and **0 CDB writes** were performed.

GitHub Actions evidence (both successfully completed):
- Newer native witness 17449516: [run 42465293411](https://github.com/BackstageTalks/tbt/actions/runs/42465293411),
  15 attempts, 14 available responses plus one 204. Provider-reported
  remaining after run: 12916.
- Archived 2016 Wimbledon native witness 7115726:
  [run 42465442647](https://github.com/BackstageTalks/tbt/actions/runs/42465442647),
  15 attempts, 12 available responses, two 204, one HTTP 400 (monthly
  calendar for July 2016). Provider-reported remaining after run: 12899.
  The 17-call difference in provider remaining between runs may include
  outside consumers: do not attribute those two extra changes to these jobs.

| Endpoint / evidence | Newer witness | Archived 2016 witness | Interpretation |
| --- | ---: | ---: | --- |
| Daily bulk odds, native keyed events | 994 | 336 | Each has two choices, but no explicit quote clock |
| Daily odds choice rows with price-shaped field | 1988 | 672 | Both sides labelled; raw values/point-in-time price not verified |
| Tournament scheduled matches by native date | 32 | 1 | Unique native event IDs in each sample; no CDB identity/import proof |
| Tournament round, *same independent AO 2023 example* | 32 | 32 | Works for this documented route, not an archived-2016 round check |
| Tournament season latest page (page 0) | 30 | 30 | First page only; pagination/completeness not proven |
| Player month events | 8 | 12 | Sample varies; not a fixed 7-row endpoint cap |
| Team month events for same ID | 8 | 12 | Response SHA-256 exactly identical to player-month in BOTH cohorts |

One research caveat: the generic bulk report labelled market `id` values in
`match_betting_odds.markets` as `unique_native_event_ids`. Those are **market
IDs, not match IDs**; do not use that metric for canonical identity or
coverage. The round sample is independent of the source witness, and the
daily odds inventory does not prove a single valid pre-match price.

Historical BP correction:
[prior run 42407952959](https://github.com/BackstageTalks/tbt/actions/runs/42407952959)
verified 200 attempts / 0 new cells with `breakpointsscored` unsupported in
all 200. After the guarded alias fix in PR #1446, the
[100-call read-back 42416694839](https://github.com/BackstageTalks/tbt/actions/runs/42416694839)
and [400-call WTA read-back 42417826366](https://github.com/BackstageTalks/tbt/actions/runs/42417826366)
independently verified 3274 **mixed statistic** cells in total, not 3274
break-point-specific fields. Both had 0 new fully serve/return-ready rows.
Therefore 200/0 is valid as a *historical failure*, but is no longer proof
that BP-enrichment should be globally disabled.

Decision: Retain the existing category/day/month batched historical collector.
Use tournament date/round/last as evidence-backed gap-specific alternatives,
not blanket replacements without non-overlap, identity and CDB delta checks.
Do not pay for both player- and team-month aliases for the same ID/month unless
there is documented incremental data. Daily odds may be a very efficient
event/selection index, but it cannot replace historical pre-match quotes or
individual market requests without valid quote timestamp and provider/market
identity verification. Spend no more calls merely to reach the operator's
300-per-test permission ceiling. No model or production route changes.

## Verified ATP 2024 100-call breakpoint-focus CDB enrichment — 2026-11-08

Authorized follow-up to test ATP where the legacy 2023 cohort had a low 47
new values / 92 calls and 70 conflicts. The existing **provider-native**
guarded statistics importer (not the read-only bulk probe) selected ATP 2024
from its current canonical gap plan, with no model changes.

[GitHub Actions run 42466110083](https://github.com/BackstageTalks/tbt/actions/runs/42466110083)
**completed successfully**, all of Acquire global CDB writer, Execute
operation, Independently verify every targeted CDB statistics publication,
Upload report, and Release global CDB writer **succeeded**. The cross-repository
lock tag was independently observed absent after release.

Exact report/read-back:
- Provider-native 100 paid attempts (including retries), 99 enriched
  matches, one empty whole-match response, **779 net-new canonical statistic
  values**, **7.79 new values per paid call**; zero conflicts and zero
  new complete serve+return-quality rows.
- Read-back `status=VERIFIED`, `persisted_new_statistic_values=779`,
  `persisted_new_per_set_matches=89`, target
  `history-2024.parquet` SHA-256
  `cc64fbe1c55e894d60bf339e15cfdbc3932ed42298c14a8c9b49199c2ba8c1fb`.
- Current ATP 2024 candidate plan: 73,092 completed matches, 39,860 already
  fully quality-ready, 2,321 eligible breakpoint-focus matches; 48,848
  on retry cooldown, 17,787 without unambiguous provider event ID, 4,136
  already with target BP fields present. **These are mutually exclusive
  selector skip reasons, not 70k safe import candidates**.
- Provider key inventory: supported `breakpointssaved` and
  `breakpointsscored` present in 99 payloads each, plus other serve/return
  and ace/DF keys. The 779 canonical cells include **mixed provider
  statistics**, NOT 779 proven break-point-only cells; aggregate report
  did not split exact new field counts by name.
- The 7.79 ATP 2024 return is close to the independently measured WTA 2023
  7.9475 return; it **does not** prove the 2024 yield will remain stable
  after the first 100, or establish trained-model benefits.
- Artifacts: `blinq-statistics-42466110083` containing
  `download_report.json`, `statistics_gap_plan.json`,
  `statistics_readback.json`, `download_progress.json`.

Decision: ATP 2024 is a validated productive cohort, but continue
ATP/WTA 2016–2026 prioritization based on **fresh persisted cells per paid
call**, not a fixed season or blanket re-fetch of BP-only gaps. Preserve
NULL-only canonical precedence, 500 reserve and global single-writer;
do not claim serve/return quality improvements from the value count alone.

## ATP 2024 next 500-call canonical import — 2026-11-08

Operator explicitly authorized 500 NEW paid attempts after the previous
100-call ATP 2024 pilot yielded 779 verified net-new statistical values.
Existing native targeted break-point-focus statistics importer was reused,
without any provider route, model, quality, or writer-contract changes.

[Actions run 42468614163](https://github.com/BackstageTalks/tbt/actions/runs/42468614163)
completed **successfully**. All of acquire owner-only global CDB writer,
execute native operation, independent canonical publication read-back, artifact
upload and owner-only lock release succeeded. The tag observed soon afterward
was a **different, later owner**, run 42469575334; do not confuse this with
failure to release the completed run's lock.

Read-back from `blinq-statistics-42468614163`:
- **500 paid attempts**, 306 enriched matches, 194 responses classified
  as conflicts and safely rejected, 0 empty whole-match results.
- **2,787 actually persisted net-new canonical statistic cells**
  (`status=VERIFIED`, 5.574 cells per paid attempt); 282 matches with
  persisted per-set data.
- 0 new fully serve/return-ready rows and 0 new ace/DF cells.
- `history-2024.parquet` independently verified SHA-256:
  `b18c0efa98ee1248ef2971d354ece216068188f1fb6529e188a9794a5afdecff`.
- 2,221 eligible candidates in the pre-run plan. The earlier 100-call pilot
  had 2,321, before its 100 selected matches entered cooldown.
- Source statistics payload key inventory observed 500 complete payloads
  with both break-point keys, but the canonical delta reported all safe
  statistical fields together: **2,787 is not proven BP-only**.
- This aggregated report does not itemize the 194 conflict reason labels.
  The guarded enricher refuses any response conflicting with existing
  authoritative statistics; it never overwrites the existing cell.

Comparison:
| ATP 2024 cohort | Paid calls | Enriched matches | Rejected conflicts | Net-new CDB values | Values / paid call |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pilot run 42466110083 | 100 | 99 | 0 | 779 | 7.790 |
| Continuation run 42468614163 | 500 | 306 | 194 | 2787 | 5.574 |
| **ATP 2024 combined** | **600** | **405** | **194** | **3566** | **5.943** |

The incremental yield fell ~28.4% relative to the pilot, with a 38.8%
conflict rate in the new cohort. **Do not repeat a large blind ATP 2024
same-order batch** merely because many CDB cells remain NULL. Next
read-only improvement: report per-reason conflict counts and per-field
net-new CDB deltas from the existing importer, then compare eligible WTA
and other ATP season windows using evidence-backed yield without changing
global budget, identity, precedence or point-in-time constraints. Production
model/forecast changes remain out of scope.

## getMatchStatistics field and conflict research — 2026-11-08 (read-only, 0 API calls)

The previous 500-call ATP 2024 artifact `blinq-statistics-42468614163`
was independently re-inspected, along with the current
`api/tbt/providers/statistics.py`,
`api/tbt/services/statistics_enrichment.py` and the operator's anonymized
`getMatchStatistics` example.

- In all **500 observed ALL-period responses**, the provider exposed
  `aces`, `doubleFaults`, `firstServeAccuracy`,
  `firstServePointsAccuracy`, `secondServePointsAccuracy`,
  `firstReturnPoints`, `secondReturnPoints`,
  `breakPointsSaved`, and `breakPointsScored`. The current
  parser already consumes these where an explicit rate/count-backed ratio
  exists; do not call this an untapped endpoint.
- `servicePointsScored` and `receiverPointsScored` were present in
  all 500 responses but are not currently mapped into strict
  denominator/reconciliation diagnostics. `secondServeAccuracy` also
  appeared in all 500, and can serve as independent validation of
  double-fault/second-serve-attempt units, *not* be confused with
  `secondServePointsAccuracy`.
- 68/500 responses carried additional winners/unforced-error/groundstroke
  breakdown keys. They are unmodeled fields with **unknown canonical
  coverage**, not automatically 68 useful new matches.
- 194/500 calls were marked `status_conflict`. The current importer
  deliberately rejects a **whole provider statistics response** when any
  parsed non-NULL existing canonical value differs. This protects the
  authoritative CDB, but may forgo separate new nonconflicting cells.
  Exact per-field conflict counts are NOT included in the aggregate artifact;
  diagnose conflict keys and numeric deltas from private provenance before
  deciding whether isolated null-only fields can be accepted.
- The attached sample supplies `ALL` saved/faced BP counts home 3/3,
  away 2/3, plus `breakPointsScored` count home 1, away 0.
  Thus opposite-side saved/faced data mathematically imply **home BP
  conversion 1/3; away 0/3**, each independently agreeing with the
  count-only `breakPointsScored` member. Current parser cannot directly
  obtain a BP return rate from the count-only field. Candidate is a
  strictly **cross-validated** derivation with preserved input provenance,
  only for safe NULL fields; no automatic mapping change approved yet.
- The same anonymized example has inconsistent periods: home saved BP
  `ALL=3/3` versus first+second set combined `1/5`; away
  `breakPointsScored ALL=0` versus set sum `1+3=4`;
  away double faults `ALL=0` versus per-set sum `0+1=1`.
  The current set parser suppresses all set-level enrichment when the set
  total **exceeds** a whole-match ace/DF total, but allows incomplete
  **undercounts**. Do not use raw set summations as canonical whole-match
  values without fully checked completeness and semantics.
- Research-only endpoint witness pack under *the configured*
  `tennisapi1.p.rapidapi.com` host:
  (a) `GET /api/tennis/event/{eventId}` for exact identity/finish,
  (b) `GET /api/tennis/event/{eventId}/statistics` for ALL + sets,
  (c) `GET /api/tennis/event/{eventId}/point-by-point` for point-level
  completeness/serving/score semantics, and optional
  (d) `GET /api/tennis/team/{teamId}/year-statistics/{year}`
  for aggregate coverage, **not direct match-level CDB supplementation**.
  Use the SAME finished match/native event ID in (a)–(c).
  An arbitrary `eventId` from another tennis API product must never
  be matched without a provider-native witness.

Priorities: (1) per-field conflict reason/delta histogram and
already-paid payload quality audit; (2) conservative cross-validated
opponent BP-saved -> conversion-rate candidate with regression tests,
including 0/0 and inconsistent set tapes; (3) denom-based service/return
cross-checks from scored raw points; (4) PBP coverage/completeness
measurement before any new paid scale; (5) validate whether 68/500 richer
stroke reports merit dedicated canonical fields. No API calls, imports,
schema upgrades or model changes were executed for this investigation.
