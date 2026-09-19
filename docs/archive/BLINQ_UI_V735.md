# BlinQ v7.3.5 — unified UI, access & services polish

v7.3.5 builds on the v7.3.4 deployment-integrity guard and combines the remaining launch-facing UI, entitlement and service work into one release.

## Access & display
- ROOKIE defaults to **2 deterministic random TOP picks per account/day**. VALUE / ESA / GAMES / SETS / Štvorhra stay visible as locked panels by default until Admin explicitly opens rows.
- Remaining offer slots are represented as locked/blurred placeholders; the underlying pick rows are **not sent to the browser**.
- Admin → **Zobrazenie** controls each public offer panel per plan with SHOW / BLUR / HIDE, unlocked row count, FIRST vs NÁHODNÉ / DEŇ selection and per-row SHOW / BLUR / HIDE overrides for rows 1–10.
- GAMES and SETS have independent server-side panel entitlements.
- Banner audiences support SHOW / BLUR / HIDE and a separate click ON/OFF rule.
- Locked rows and panels show a compact `Vyžaduje <PLAN>` cue and open the membership upgrade dialog.

## Membership dialog
- Rebuilt in the native BlinQ dark/teal/purple visual language.
- Shows current plan, recommended plan, validity, the required-tier badge, primary upgrade CTA and plan comparison CTA.
- Copy is editable through `web/config/site-content.json`.

## Login, loading & footer
- Stronger shared BlinQ ambient background on login and loading screens.
- Subtle bottom-right BlinQ watermark on auth/loading and watermark-style footer branding.
- Login subtitle is smaller/muted and typography is unified.
- Language chips use the BlinQ green/dark palette.
- Footer status no longer calls stale data LIVE. LIVE is only shown for a fresh radar scan; ordinary feed state uses current/older/waiting/error wording.

## Support / INFO / storage
- Durable private-service storage uses the shared fallback chain:
  `BLINQ_ADMIN_STORAGE_CONNECTION_STRING` → `BLINQ_STORAGE_CONNECTION_STRING` → `BLINQ_MEDIA_STORAGE_CONNECTION_STRING` → `AzureWebJobsStorage` → Firestore.
- Support falls back to email delivery when durable storage is down and Resend is configured (`RESEND_API_KEY` + `BLINQ_SUPPORT_TO_EMAIL`). If neither path works, it fails clearly instead of pretending success.
- User-facing support/offline copy is localized and editable in `site-content.json`.
- INFO/history storage health is kept distinct from LIVE Radar freshness.

## Deployment integrity
- Keeps the v7.3.4 protection that prevents long-running old data workflows from redeploying an older frontend.
- Frontend marker: `blinq-web-735`.
- HTML/release marker: `UI 7.3.5` / `/release.json`.
- CI verifies the deployed 7.3.5 HTML, CSS marker and release JSON.
