# BlinQ 7.3.6-r9

Focused cleanup on top of r8 autonomous LIVE radar.

## Fixed
- Admin publish path restored: `publishUiConfig()` now calls `/api/v1/admin/ui-config`, so ROOKIE SHOW/BLUR/HIDE and row settings can be published, not only saved as a browser draft.
- Access/upgrade hover hint no longer flickers when the pointer moves from the locked header item into the hint.
- Footer reduced to BlinQ watermark + UI version on the left and language switcher on the right.
- Footer is visible on the homepage as well as content routes.
- Legacy VIP/benefit strip above the footer is disabled; it was a leftover presentation block.
- Frontend cache patch advanced to r9 / p=9 without changing release 7.3.6 / asset revision 7360.

## Verification
- 53 focused Python tests passed.
- `tests/test_v736_ui_regression_contract.js` passed.
- app.js/auth.js/responsive.js syntax checks passed.
