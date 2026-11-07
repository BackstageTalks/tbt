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
