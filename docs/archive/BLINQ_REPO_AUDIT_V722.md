# BlinQ repository audit — v7.2.2

Base: v7.2.1 LIVE + Set-2 + SG fixed repository.

## Added / changed

- Public GAMES and SETS tabs now consume server-authorized `sg_picks`, split by `market=games|sets`.
- GAMES/SETS stay explicitly projection-only; no odds/edge/EV placeholders are converted into betting prices.
- ELITE/Legend/GOAT/admin can receive SG rows; Rookie/PRO remain blocked server-side by the existing entitlement policy.
- SEE ALL can include authorized ESA and SG projection rows.
- Mega-data protects a final refresh budget within the same global API cap and publishes the feed after enrichment.
- Refresh writes a machine-readable `refresh_report.json`.
- Mega-data runs production preflight and emits a consolidated launch gate artifact.
- Support tickets can optionally send a Resend email notification with deterministic idempotency key; storage remains canonical.
- Admin diagnostics expose whether support email is configured.
- CI supports an optional deployed health smoke test and verifies release `7.2.2`.
- Release/UI cache revision bumped to 7.2.2 / 7221.

## Local validation

- Focused v7.2.2 launch tests: 24 PASS.
- Broad suite without the Azure import smoke: 402 PASS, 1 skipped, 8 failures caused only by missing local `pyarrow`.
- GitHub CI installs `pyarrow` from `api/requirements-train.txt` and Azure Functions from `api/requirements.txt` before the full suite.
- Python compileall: PASS.
- `node --check web/app.js`: PASS.
- `node --check web/auth.js`: PASS.
- GitHub workflow YAML parse: PASS.

## Deliberately not faked

- SETS/GAMES and ESA bookmaker prices remain unavailable until a real price/line source is observed and validated.
- LIVE Set-2 edge/EV is emitted only if the provider returns a supported Set-2 winner market.
- Doubles stays disabled pending a separate pair/team model and stable provider identity contract.
