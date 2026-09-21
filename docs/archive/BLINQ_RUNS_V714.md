# BlinQ v7.1.4 — data-run cleanup

## Fixed Environment enrichment
- Full-range defaults now start at 2021-01-01, `limit=0`, blank end = today UTC.
- Added configurable Open-Meteo/geocoder `max_requests` (default 12000). This is separate from the Tennis RapidAPI quota.
- Fixed the important `force + static_only` bug: the workflow no longer passes mutually-exclusive `--force` and `--complete-static` together.
- `force=true` now really re-resolves/overwrites every in-range row.
- Each environment run uploads `environment_enrichment_report.json` as a GitHub artifact.

## Rebalanced mega-data
The current production preflight shows event statistics as the largest data gap, SG second, while Aces/DF already have a useful corpus. `mega-data` therefore now runs:
1. small provider probe,
2. primary generic statistics sweep,
3. SG targeted enrichment,
4. smaller ACE/DF top-up,
5. small history catch-up,
6. statistics tail using every request still available,
7. zero-API post-run statistics inventory.

Unused request headroom rolls forward after every phase. The global `max_requests` cap is never intentionally exceeded.

## Better provider probe
Statistics probing now captures actual provider statistic item names/keys, sample item shapes, supported aliases and unsupported item names. This lets us fix the event-statistics adapter from evidence instead of guessing.

## Suggested operations
- Environment overnight overwrite: workflow `Environment enrichment`, mode `write`, force `true`, static_only `true`, limit `0`, start `2021-01-01`, end blank, max_requests `12000`.
- Tennis quota consumption: workflow `Tennis data and predictions`, mode `mega-data`, set only the remaining request budget you want to spend.
