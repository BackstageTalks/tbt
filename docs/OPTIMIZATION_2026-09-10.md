# BlinQ 6.5.7 optimisation pass — 2026-09-10

This pass keeps the uploaded repository as the baseline and focuses on functional truth, mobile usability and a lighter visual footprint.

## Functional changes

- Firebase signup now requests `VERIFY_EMAIL`; unverified users cannot open the prediction feed or Admin.
- Login detects an unverified Firebase account and exposes a resend-verification action.
- Account page now contains profile, avatar style, verified-email status, access/trial details, password reset and sign-out controls.
- Membership checkout links are accepted only as explicit HTTP(S) destinations; plans without checkout remain informational instead of pretending to be purchasable.
- GOAT is labelled `INVITE ONLY`; this is intentionally separate from email verification.
- BTTS uses an internal beta route and never silently falls back to Dashboard.
- Manual and automatic feed refreshes also refresh runtime UI configuration.
- Banner event telemetry has a lightweight instance-local flood guard in addition to payload validation.
- Language navigation currently exposes only EN/SK because those are the only supported locale paths.

## Visual / responsive changes

The reversible block at the end of `web/responsive.css` is marked `BLINQ LIGHT POLISH`.

- Account desktop layout: profile/access summary followed by a centred 3+2 plan layout.
- Account tablet: 2-column plan layout; phone: compact single-column membership cards.
- LIVE status is compact and hidden on non-data routes such as Account/FAQ/Admin.
- Desktop-only information is restored behind sensible breakpoints instead of being globally hidden.
- Banner rows respect the configured row preset on desktop and deliberately reduce inventory on smaller screens.
- Footer hierarchy is quieter; technical model identifiers are shortened visually while the full value stays in the title attribute.

## Asset weight

`web/assets` was reduced from roughly 9.2 MB to roughly 2.9 MB without changing public asset paths. Large membership/avatar sources were resized for their real rendering size, the favicon was reduced to 512 px, and the logo SVG was stripped of the oversized editing/metadata payload while preserving its appearance.

## Validation

- JavaScript syntax checks pass.
- Firebase sign-in, refresh-race and email-verification JS tests pass.
- Focused web/auth/admin contract tests pass.
- Full Python suite: 235 passed; 8 tests require the optional `pyarrow` package and fail only because it is not installed in the current execution environment.
## 6.5.9 / 6.5.10 real-device test build

- Main hero is now a fixed full-width rotating advertising zone with 1–4 configurable creatives. Admin controls the number of creatives, auto-rotation, dots and the global rotation interval (3–300 seconds). Each creative keeps its own image/mobile image, link, campaign, schedule, sponsored state and watermark.
- Dashboard preview cards were compacted for the new top-navigation layout. The rich Prime signal rows and the old per-card analysis link are intentionally removed from the dashboard preview; the panel-level `See more` opens the dedicated section with 3–5 published picks.
- Frontend cache query keys and `ui_revision` were advanced to 6.5.10 for real-device deployment testing.

Validation for this build: 34 focused UI/admin/access tests pass, all 3 Firebase JS auth tests pass, and the full Python suite is 240 passed / 8 unavailable because the execution environment does not contain optional `pyarrow`.
