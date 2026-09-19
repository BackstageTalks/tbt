# BlinQ v7.2.1 — LIVE / Set-2 / SG integrity repair

Base: `v7.2.0 launch` repository snapshot.

## Production fixes

- Removed the unsupported Azure Static Web Apps timer-trigger dependency from Comeback LIVE Radar.
- ELITE/Admin HTTP polling now schedules LIVE scans; provider calls are cached for 45 seconds and alert publication is idempotent.
- LIVE status remains available if private insight storage is temporarily unavailable.
- Added a separate historical conditional projection: `P(win set 2 | lost set 1)` for internal PRIME candidates.
- The Set-2 projection is generated at refresh time from historical structured set scores; it is not the Match Winner probability reused under another name.
- Added real provider parsing for `Set 2 Winner`, `2nd Set Winner`, `Second Set Winner`, and `Winner - Set 2` style markets.
- When a real two-way Set-2 market exists, LIVE Radar calculates de-vig fair probability, edge and EV. If the provider does not expose the market, no price/value is invented.
- WATCH alerts may include the conditional Set-2 projection and real LIVE Set-2 price diagnostics. CONFIRMED logic remains conservative: break lead or second-set win.

## SG / score data contract

- Score enrichment schema upgraded from v1 to v2.
- Structured score stats now retain set-1/set-2 games and `p1/p2_second_set_won`.
- Targeted SG enrichment revisits old aggregate-only score rows until schema-v2 facts are available.
- SG report schema upgraded to v2.
- This enables honest historical conditioning for “lost set 1 -> won set 2”.

## Provider / data-run diagnostics

- Provider probe now inspects current LIVE events and Set-2 odds samples.
- `second_set` is a separate capability bucket in the odds report.
- Mega-data artifacts now retain SG and ACE run summaries in addition to history/statistics/provider reports.
- Direct SG and ACE workflow modes upload their own report artifacts.
- Stale mega-data tests were updated to the v7.2.0/v7.2.1 launch allocation (small history safety sync, SG/ESA priority, unused budget rollover).

## Validation in this sandbox

- Changed-area regression suite: 58 passed.
- Earlier focused LIVE/Set-2/score/mega suite: 22 passed.
- Python compileall: PASS.
- `node --check web/app.js`: PASS.
- `node --check web/auth.js`: PASS.
- Workflow YAML parse: PASS.
- Broad suite without Azure import smoke: 398 passed, 1 skipped; 8 parquet tests could not run because local `pyarrow` is unavailable.
- Azure import smoke could not run because local `azure-functions` is unavailable.
- Repository CI installs both dependencies from `api/requirements.txt` and `api/requirements-train.txt` before running the complete suite.

## Recommended launch sequence

1. Run GitHub CI on the v7.2.1 branch/snapshot.
2. `history-audit` (no Tennis API quota).
3. `production-preflight` (no Tennis API quota).
4. `mega-data` with the intended request budget.
5. Run `provider-probe` during active tennis to confirm real Set-2 market coverage.
6. Deploy only after CI is green, then test Admin -> Info & LIVE and an ELITE account.
