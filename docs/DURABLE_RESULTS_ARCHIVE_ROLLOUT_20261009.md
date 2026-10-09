# Durable Match Status → Results archive (2026-10-09)

Production recovery for the 2026-10-08 Results display.

- The authenticated Match Status worker saves its verified terminal snapshot,
  then materializes *previously deployed* Match Winner selections from that exact
  snapshot and writes them into the Azure Table `BlinQAdminConfig` using a
  separate `settled-results-archive-v1` partition.
- Before each archival write, publication timing, verified terminal evidence,
  selected player, real issued odds, and supported public Results categories
  are checked. Unissued, excluded, nonterminal, post-start publications, and
  TOP200-only rows are not written into this Results archive.
- Every changed daily archive shard is read back; the workflow fails closed if
  the persisted result is unreadable. Repeated runs are idempotent and do not
  consume tennis provider API requests for archiving.
- Every authenticated `/api/v1/feed` read merges durable Results with the
  immutable released feed **before** existing plan/age entitlements and KPI
  calculation. The same semantic selection/event identity prevents duplicates.
  Existing canonical settlement and immutable publication prices have priority.
- The original `tbt-predictions-v1` `feed.json` and `ledger.json` are never
  rewritten by the Match Status job. No prediction model is promoted.
- After new betting day at 06:00 Bratislava, Results retain eligible previous-
  day results in the archive even when the compact per-day Match Status snapshot
  moves to the next day's cohort. The default "Today" filter still means the
  current betting day; users can choose All time / previous days.

## Production verification

1. Green `Test and deploy` CI and exact deployed SHA.
2. First fresh 30-minute `Hourly prediction match status` action returns
   `results_archive.verified=true`; `results_archive.added` reports new
   persisted market rows and repeated runs return `added=0`.
3. Authenticated Results history displays old settlements after the 06:00
   rollover without duplicated selections; KPI values use the same rows.
4. Any storage/write/readback failure is an error, not an empty successful job.

PR #421: https://github.com/BackstageTalks/tbt/pull/421
