# ELITE Results — dynamic current Admin scope (2026-11-09)

## Goal / acceptance
Results → Dnes → ELITE shows only published bets from the **currently active categories and row slots** set in Admin → Zobrazenie. Record, hit rate, quoted odds, ROI, units, cards and the sample numerator/denominator derive from the same authorized issued category cohort; settings changed and published later require no code edit or manual reload.

## Binding decisions
- The Admin persisted runtime config and the API's server-produced `member_result_rules` remain authoritative. No hard-coded ELITE market list or new access writer.
- Historical settled Results, issued wager contract, accepted prices, model, CDB, RapidAPI budget and external-cron scheduler remain unchanged.
- A derived ESÁ leader bridge (`ace_winner_issued=false`, `projection_only`) is presentation-only; it is not an independently issued VIAC ES bet and may not enter the sample.

## Implemented / tested
- Merged implementation PR [#1508](https://github.com/BackstageTalks/tbt/pull/1508), commit `9292aa0ed75507095b28829578584a8776cbd534`.
- The prior bare membership key allowed TOP permission to leak to hidden ACCA when the two publications shared event/market/selection. The new rule retains the granting Admin tab and rejects disabled, hidden and blurred categories, including `visible_picks=ALL`.
- Denominator now requires explicitly issued source publications/legacy receipts; presentation-only VIAC ES bridges cannot inherit the ESÁ issue and inflate the sample.
- After every successful Admin publish and durable config read-back, the existing authenticated feed is reloaded to obtain fresh membership rules.
- PR full CI / real Chromium tests: [run 42661585696](https://github.com/BackstageTalks/tbt/actions/runs/42661585696), **successful**. The browser fixture reproduces a 62-pick overall pool vs 11 ELITE-eligible issued bets, 9 settled, exercises TOP first five, VALUE/ESÁ/VIAC ES, excludes 30 hidden ACCA and other locked markets, and dynamically toggles ACCA, Games, Most Aces, Sets and TOP 5→6.

## Production release incident and safe recovery
- The main run [42662983669](https://github.com/BackstageTalks/tbt/actions/runs/42662983669) for `9292aa0` was **cancelled** following a newer concurrent audit-only main commit. Successful PR CI and merge alone do not prove deployment.
- A live read-only check of `/deployment.json` after cancellation returned `git_sha=388e830eb965e84d65fcc7d80a3d6c683cdcc4da` (older than the ELITE fix).
- This **docs-only release checkpoint** requests deployment of the then-current main through existing `ci.yml` using the documented `[deploy-current]` marker and serial `tbt-production-deploy` lock. It does not overwrite any published data, reconfigure the UI or change infrastructure scheduling.

## Release / verification gates
1. Main full CI and Chromium browser contract pass on the resulting exact commit; no unrelated in-progress deployment bypassed.
2. Guarded Azure deploy succeeds. Independently fetch production `deployment.json`, HTML and `app.js` with fresh cache-busting and verify that the SHA and asset hash correspond to the deployed commit.
3. Public `/api/v1/ui-config` still reports runtime-configured durable Admin settings, including current ELITE visibility.
4. Authenticated live Results → ELITE vs ALL comparison on the same betting-day period must be verified independently when session access is available; do not claim live counts from test fixtures.
5. If live behavior regresses, preserve the deployed evidence and use the existing guarded exact-current rollback/redeploy procedure; do not edit Results ledger, CDB, Admin settings or frozen contracts.

## Status at checkpoint
Implementation: MERGED. PR regression: TESTED. Production ELITE release: **NOT YET VERIFIED** after interrupted main deploy. Authenticated ELITE live count reconciliation: **OPEN**.
