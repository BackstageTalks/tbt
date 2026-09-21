# BlinQ 7.3.6-r46 — FREE membership/account copy separation

## Changes
- Internal membership id stays `rookie`; public account/upgrade UI renders it as `FREE`.
- FREE remains in the membership offer as the permanent base tier.
- An authenticated `EXPIRED` non-admin user can explicitly reactivate FREE from the account membership UI.
- Reactivation is server-side constrained to `rookie + active + no expiry`; suspended/admin users cannot use it.
- Account membership cards use Admin **Detailný popis** (`description`) as their visible copy.
- Admin **Interná poznámka** (`note`) is retained only as the heading above the feature list in upgrade/membership offer cards (e.g. `Obsahuje:`).

## Doubles readiness review
The codebase already contains an isolated `DOUBLES-ELO-v1` pipeline and does not reuse singles probabilities.
Production publication remains fail-closed until the separate doubles history release is ready.
Activation gate: at least 200 completed doubles matches and >=90% explicit member-identity coverage.
A publishable doubles pick additionally requires pair/member history, data depth >=0.35, model probability >=0.58, real Match Winner odds 1.35–3.50 and EV >=2%.

One-time backfill workflow:
- workflow: `Tennis data and predictions`
- mode: `doubles-data`
- lookback_days: `365`
- max_requests: `10000`
- start/end: blank

The backfill is resumable. After the gate becomes ready, normal refresh discovers upcoming doubles, builds probabilities, requests real Match Winner odds and publishes only qualifying selections.
