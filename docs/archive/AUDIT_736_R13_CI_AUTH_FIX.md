# BlinQ 7.3.6-r13 — CI auth runtime fix

- Restored `adminPayments`, `adminAddPayment`, and `adminAudit` client API wrappers accidentally removed during support cleanup.
- These wrappers are still used by the current Admin Accounts UI and map to live backend routes.
- Bumped frontend patch/cache marker to r13 / p=13, including auth.js.
- Release stays 7.3.6 / asset revision 7360.
- Exact Node CI frontend checks pass locally after the fix.
