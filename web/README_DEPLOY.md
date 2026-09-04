# BlinQ web v3 – deploy

Copy the CONTENTS of this package directly into the repository `web/` directory.
Azure Static Web Apps already deploys `app_location: web`.

## Included now

- Dashboard + BlinQ Prime Picks
- Prime Picks Top 10 carousel ranked from real model probability + data depth + signal agreement
- visible-but-locked plan navigation
- Dashboard / Prime Picks / Tournaments / Players / Stats / Model Performance / Backtests / Account shells
- Learn pages
- larger account area, plan entitlement, Upgrade dialog shell
- Engine Talks goat placeholder in the sidebar and BlinQ racket logo in the main header
- header sponsor slot
- configurable top and bottom banner zones with 1–4 layouts
- Admin Banner Manager UI shell (only rendered when account plan is `admin`)

## Important technical boundaries

`Value Picks` is intentionally not faked: it remains locked until a real bookmaker odds feed is connected.
`Ace Picks` and `Games & Sets` remain locked until their dedicated data/model pipelines exist.

The Admin Banner Manager currently saves preview changes into browser `localStorage` and can export JSON. Global publishing/upload must later be connected to an authenticated admin API + persistent storage (for example Supabase Storage/config table). This frontend does not pretend local preview is a server-side publish.

## Plan configuration

Plan visibility/access is controlled in `ui-config.json` through `allowed_plans`.
Current demo account is set under `account.plan`.

Normal production flow should replace this static account plan with the authenticated user's entitlement from the backend.
