# BlinQ 7.3.6-r3 stabilization pass

This patch is based on v7.3.6-r2 and deliberately keeps the public release contract at **7.3.6 / asset revision 7360 / blinq-web-736**. Only the internal patch cache marker is bumped to `p=3`.

## Visual corrections
- Restored subtle BlinQ watermark on the loading screen.
- Added a subtle fixed BlinQ watermark on normal member pages for screenshots; admin remains clean.
- Cleaned the Daily Hub final action column: `Detail` no longer has a clipped/dangling arrow at the right edge.
- Generic header `Upgrade` no longer marks PRO as a required level.
- Required-level treatment appears only when the upgrade flow originated from locked content.
- Admin role is displayed separately from membership in the upgrade dialog; membership is no longer replaced by `ADMIN`.
- Removed the redundant bottom benefit strip from the upgrade dialog.

## Data/UI correctness
- Tournament location is shown only from explicit provider/API location fields. It is never guessed from the tournament title.
- Membership feature bullets are now driven by `web/config/membership-tiers.json`.
- Generic upgrade copy is kept in `web/config/site-content.json`.

## Admin -> System diagnostics
Added dedicated cards for:
- PLAYER IMAGES
- TOURNAMENT LOGOS
- SUPPORT STORAGE
- INFO STORAGE
- LIVE DATA

The backend diagnostics endpoint returns media reference/fallback counts without spending external provider requests.

## Regression protection
- Added `tests/test_v736_stability_contract.py`.
- Added dependency-free Node UI contract `tests/test_v736_ui_regression_contract.js`.
- CI now runs the UI contract automatically.
- Release/cache contract verifies that local CSS/JS `v=` revisions stay aligned with `ui-config.json`.

## Local verification
- JavaScript syntax: PASS.
- Python compileall: PASS.
- New UI contract: PASS.
- Focused UI/regression set: 44 PASS.
- Broad feasible local suite: 500 PASS, 1 skipped; 8 parquet tests could not run locally because this container does not have `pyarrow` installed.
- The Azure API smoke test also cannot be collected locally without the Azure Functions package; CI installs runtime requirements before running it.
