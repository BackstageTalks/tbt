# BlinQ v5 — data integration runbook

This update keeps the page structure fixed and starts filling the betting sections from real current data without inventing new market models.

## 1. Environment enrichment resume

The default environment run is now **missing-only**:

- rows with no `_tbt_environment` are processed;
- rows already resolved are skipped;
- rows already attempted but unresolved are also skipped.

This prevents a restarted six-hour GitHub-hosted run from spending most of its time retrying the same unresolved venues.

Use the normal first pass with:

- mode: `write`
- force: `false`
- retry_unresolved: `false`
- limit: `0`
- same start/end range as the previous run.

After the missing-only pass has covered the range, run a separate second pass with `retry_unresolved: true`. The second pass benefits from the conservative tournament aliases added for common unresolved locations (Miami, Indian Wells, US Open, Wimbledon, Cincinnati/Mason, Dubai, Eastbourne, Adelaide, Washington and Kursumlijska Banja).

Historical Open-Meteo archive weather remains research/evaluation metadata and is explicitly not treated as point-in-time training data.

## 2. Current player presentation data

`Player card enrichment` maintains a private current player-asset release. It uses:

- ATP/WTA current ranking snapshots first;
- per-player ranking fallback only when current rank/country is missing;
- cached player image by player id;
- country alpha-2/alpha-3 from ranking metadata.

Current rankings/photos/country are presentation metadata only. They are never backfilled into historical training rows.

Recommended first production pass:

- max players: `0` (all current feed players)
- max photo requests: `250` (increase later if desired)
- max fallback ranking requests: `100`
- refresh photos: `false`

Repeated runs reuse cached photos and profiles.

## 3. Current betting sections

During `Tennis data and predictions` -> `refresh`, the pipeline can now use provider-1 current pre-match Match Winner odds for the current BlinQ betting day.

Default betting day: `06:00 Europe/Bratislava` -> `05:59:59` next day.

The market layer does **not** change the Match Winner model probability. It adds a current market snapshot and derives:

- de-vigged implied probability;
- model-vs-market edge;
- expected value (`p * decimal_odds - 1`).

Dashboard outputs now available from real current Match Winner data:

- **Prime Picks**: all Match Winner predictions above the configured probability threshold, with no odds requirement or count limit;
- **Top 10 Daily Picks**: odds-backed positive-edge shortlist, max 10;
- **Value Picks**: positive edge, selected odds > 1.70 and max 15 percentage-point gap between the two de-vigged implied probabilities.

Aces/Double Faults and Sets/Games remain intentionally empty until their real model outputs are published. No synthetic or placeholder bets are generated.

Recommended refresh inputs:

- mode: `refresh`
- max requests: enough for fixtures/history refresh plus odds, normally `750`
- market odds max events: `120`
- betting day start hour: `6`

The refresh summary reports requested/available odds coverage and the number of Top Daily / Value picks. If real provider odds exist but coverage is still zero, inspect one raw event odds payload and update only the parser; do not fabricate markets.

## 4. UI presentation

Prime cards can now display current `Odds`, `Edge` and `EV` when an odds snapshot exists. The match detail dialog displays the same market snapshot.

Player cards use cached photos when available and otherwise retain the safe initials fallback. Rank/country and data depth remain visible.

Production entry remains `/follow-the-data/`.

## 5. Workflow concurrency

Long-running environment enrichment no longer blocks the manual **Test and deploy** web/API deployment.

The intended concurrency domains are now:

- `tbt-production-deploy` — Azure web/API deployments only;
- `tbt-history-data-writer` — operations that can modify the shared `tbt-data-v1` history release, including environment enrichment;
- `tbt-player-assets-writer` — current player photo/ranking asset refreshes;
- `tbt-environment-audit` — read-only environment coverage audits.

`Tennis data and predictions` remains serialized with the history writer because `refresh` currently checkpoints recent completed history and request-budget state into `tbt-data-v1`. Running it concurrently with environment enrichment could race two writers against the same committed release manifest. Ordinary UI/API deployments are safe and no longer wait for environment enrichment.
