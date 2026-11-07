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
