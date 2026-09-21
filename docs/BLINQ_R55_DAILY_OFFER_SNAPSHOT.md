# BlinQ 7.3.6-r55 — R52 baseline consolidation + daily offer snapshot

**Baseline:** user-provided `tbt-main-736-r52-projection-odds-sg-diagnostics(1).zip`.

r55 intentionally excludes the abandoned bookmaker experiment. It consolidates the approved post-r52 fixes and changes the homepage offer from a shrinking pre-match list into a stable betting-day publication snapshot.

## Included post-R52 fixes

- SEE ALL uses one consistent 8-column contract; projection markets no longer shift values under the wrong headers.
- ACES / Double Faults / Games / Sets never render a missing price as `0.00`; a provider-backed price is shown only when real, otherwise `—`.
- Projection odds discovery uses the configured market-odds event allowance instead of the old first-40-event starvation pattern.
- Projection market-name parsing covers the provider variants added in r54.
- Player-photo resolution/fallback/cache handling is shared by Predictions and Results.

## r55 daily offer contract

The BlinQ betting day is Europe/Bratislava 06:00 -> 06:00.

- `upcoming` stays future-only for event discovery.
- TOP / Short Odds / Value / Doubles / Aces / Double Faults / Games / Sets are daily publication snapshots.
- An already issued row remains visible after its match starts and disappears only after the next betting-day boundary.
- Existing issued rows keep their original order and immutable published snapshot. Newly qualifying rows may append.
- A prior pending/unconfirmed row is never carried forward after it disappears; this prevents first publication after match start.
- ROOKIE stable-random allocation remains durable for the whole betting day. Since its assigned row is no longer removed at start, the same daily pick remains visible rather than being sampled from the shrinking remainder.
- PRO finite-prefix views remain stable because the daily offer preserves morning order and only appends new rows.

The UI marks rows whose scheduled time has passed with `ZAČATÉ / STARTED / ZAHÁJENO`; the row remains readable as the day's published record.

## Validation

- Repository contract audit: PASS (`736-r55`).
- Frontend runtime/auth/Firebase/UI regression checks: PASS.
- Focused r51/r52/r54/r55 + entitlement/publication tests: PASS.
- Broad Python suite excluding the environment-only Azure import: **745 passed, 1 skipped; 8 failures are exclusively parquet tests because this sandbox lacks `pyarrow`**.
- `tests/test_v700_api_smoke_contract.py` cannot collect here because the sandbox lacks `azure.functions`; the repository dependency remains declared for CI/deployment.
