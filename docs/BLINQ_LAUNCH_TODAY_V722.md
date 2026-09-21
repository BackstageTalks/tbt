# BlinQ v7.2.2 — launch-today runbook

## What v7.2.2 closes

- GAMES and SETS are no longer hard-coded COMING SOON. They publish only as honest MODEL projections from stored structured scores; no bookmaker odds, edge or EV is invented.
- ESA remains a projection module and is included in the same launch gate.
- Mega-data reserves part of the operator's global request cap for a final `refresh`, so the newly enriched corpus is immediately used to generate and publish the current prediction feed.
- Mega-data then runs the zero-Tennis-API production preflight and writes one consolidated launch gate artifact.
- LIVE keeps the Set-2 projection separate from match-winner probability. Set-2 odds/value are shown only when the provider actually supplies a supported live market.
- Support tickets remain durable in BlinQ storage and can additionally notify support by email through Resend. Email failure never loses the ticket.
- CI can optionally smoke-test the deployed `/api/health` endpoint when `TBT_PRODUCTION_URL` is configured.

## Parallel launch tracks

### Track A — code / CI

Upload v7.2.2 to a branch and let normal CI run. Do not merge if CI is red.

### Track B — data (can run while CI is running)

Run GitHub Actions → Tennis data and predictions:

- mode: `mega-data`
- max_requests: `10000`
- lookback_days: `1095`
- ace_target_samples: `18`
- ace_lookback_days: `550`
- sg_target_samples: `24`
- sg_lookback_days: `730`
- promote: `false`

The 10k cap now includes a protected final refresh. Do not start a second provider-heavy writer in parallel with this run.

The mega artifact includes:

- provider probe
- history audit
- before/after statistics inventory
- SG enrichment summary
- ESA enrichment summary
- final refresh report
- production readiness report
- `launch_gate.json` / `launch_gate.md`

### Track C — runtime configuration (can run while A/B are running)

Required existing production settings remain unchanged (RapidAPI, Firebase, data-repo token, Azure deploy/storage).

For support email add:

- `RESEND_API_KEY`
- `BLINQ_SUPPORT_TO_EMAIL`
- optional `BLINQ_SUPPORT_FROM_EMAIL` (otherwise `BlinQ Support <support@blinq.sk>`)

For post-deploy smoke add GitHub variable:

- `TBT_PRODUCTION_URL=https://<production-host>`

Admin diagnostics should show persistent admin storage (`azure_table` or `firestore`) and `support_email_configured: true` when email is wired.

## Convergence / deploy

When CI and mega-data both finish:

1. Open `launch_gate.md` from the mega-data artifact.
2. History must be clean.
3. SG and ESA sample gates should be ready. A day with zero current SG/ESA candidates is allowed; sample readiness and current candidate count are different things.
4. Missing live Set-2 odds is a warning, not fabricated into a value bet. LIVE remains projection-only for that event.
5. Production preflight must not be blocked.
6. Merge/deploy v7.2.2 only after those gates are acceptable.
7. Deploy **after** mega-data so Azure packages the newly published feed, not the previous prediction release.
8. In Admin verify diagnostics, publish one Premium Info message, then run `Scan LIVE teraz`.

## Not launch blockers

- Doubles stays disabled until it has a separate validated team/pair identity model.
- Automatic card/payment-provider reconciliation is not required for the current payment-link/manual-ledger flow.
- Binary banner upload is not required for launch because banner URLs/assets are already editable; it is an admin convenience feature rather than a prediction/runtime dependency.
