# PropLine evening odds archive (new system, 17 Nov 2026)

## Goal
Collect actual prematch tennis ESÁ prices, with strict bookmaker provenance, at
23:00 Europe/Bratislava every day. Preserve immutable JSON on Google Drive,
with verified private GitHub recovery storage. This is a market evidence archive,
**not** a reason to change the sport-model picks, issued offers, CDB, web, TG or
historical prices.

## Provider and quote validity
- One PropLine FREE tennis odds API request each capture. Preserve provider raw
  payload and API capture timestamp. Require provider quota header and reserve
  at least 150 requests, serialize with PropLine nightly closeout.
- Store bookmaker N+ ace milestones separately from verified **complete**
  bookmaker same-line O/U pairs. N+ threshold equivalence is metadata, not an
  independently available Over/Under offer. DFS/pick'em stays research-only.
- Keep native event and player identity, market origin, bookmaker, start and
  capture timestamps, odds and original provider payload. Never infer prices.
- Capture all verified prices in scanned prematch events, including other dates,
  in `observed_prematch_priced_events`; target-day events remain separate.

## Automation
- Existing **external** 23:00 Europe/Bratislava clock, not GitHub schedule.
- New workflow: `.github/workflows/propline-evening-odds.yml`.
- New event: `blinq-propline-odds-tick`.
- Legacy external event `blinq-fortuna-evening-odds-tick` accepted only as a
  transition alias until the real external scheduler is reconfigured/verified.
  DO NOT create a second external task; change only the existing event name.
- Workflow validates and hashes the exact JSON, archives it in private
  `tbt-data:research/propline-evening-odds/<day>/propline-<runid>.json`,
  verifies GitHub readback, then creates/reads back a file on Drive.

## Google Drive
- Folder: `PropLine` (ID `1C7_B2LB37IVTK9gBu2TT9dSj5XClIUKh`).
- `propline.json`: human-readable configuration; **NOT** a market snapshot.
- Daily immutable files: `propline-YYYY-MM-DD-RUNID-HASH16.json`.
- Reuses `BLINQ_DRIVE_WRITER_JSON`, or the existing `BLINQ_DRIVE_READER_JSON`
  service-account credentials as a fallback. The identity requires **Editor** on
  the PropLine folder. The MoviOdds folder's existing ACL does not confer
  permission here. No credential is logged or copied to the repo.
- Any upload or readback mismatch fails the workflow; private recovery data
  and Actions evidence remain accessible. A GitHub 204 or workflow green
  alone is not proof of a Drive archive.

## Removed legacy code
Fortuna HTML scraper, browser preflight, its specialized morning reader and
their Fortuna-only tests are retired. The morning pipeline already uses
API Pro -> PropLine -> MoviOdds pre-start fallback where contracts match;
this collector is research-only and does not override that live enrichment.

## Morning attachment from the nightly PropLine archive (17 Nov 2026)
- The existing live priority is unchanged: Tennis API Pro -> live PropLine
  -> MoviOdds, followed by the approved statistical ESÁ fallback.
- Only during the *new morning refresh*, the optional reader uses the latest
  same-betting-day JSON in `tbt-data:research/propline-evening-odds/YYYY-MM-DD/`.
  It consumes no PropLine or RapidAPI requests; Google Drive remains the
  independently checked archival destination.
- The read is fail-closed for missing files, stale (>24 h) captures, partial
  scans, malformed source, timestamp or player identity collisions.
  Provider raw-event SHA and parsed quote equivalence are checked before use.
- It attaches only a genuine complete two-sided *sportsbook player Aces O/U*
  at the same model-derived half-ace line, to the same selected player in the
  same scheduled fixture. Candidate identity, model, counts and model
  selection remain unchanged; API-backed, priced, or issued picks retain
  their original price. Price must be >= 1.50 and must meet the existing
  verified-ace-odds contract.
- Multiple sportsbooks quoting the same exact contract are resolved
  deterministically by highest valid captured Over quote and bookmaker key;
  a conflicting duplicate from one bookmaker is rejected.
- N+ milestones, fantasy/pick'em, match-total Aces and Most Aces are **not**
  promoted to an O/U bet. Most Aces settlement rules remain unverified.
  When no eligible quote exists, the existing local-statistical price policy
  is unchanged.
- Price provenance includes bookmaker, provider event ID, native market ID
  and exact capture time; 23:00 quotes are historical observations, **not**
  a guarantee of live price availability at 06:00.
- Independent validation still requires a real 23:00 external tick, private
  JSON read-back and Drive read-back, followed by a fresh morning publication
  without revisions to already-issued cards. Offline fixture tests alone
  are not that evidence.

## Acceptance and limitations
1. Verify offline parser regressions + Drive writer tests and full repository CI.
2. Verify no old Fortuna module is imported by active code.
3. Verify actual external tick at 23:00 using the **new workflow**, exact JSON
   and matching Drive readback, plus no adverse effects on CDB or publication.
4. If Drive service-account ACL or secret is missing, treat as BLOCKED,
   not as a successful automatic Drive archive. Never delete historical raw
   tbt-data evidence to conceal incomplete migration.

Current status: Google Drive folder and `propline.json` were created and
independently retrieved. Automated Drive writing and the first real external
23:00 tick have not yet been verified.
