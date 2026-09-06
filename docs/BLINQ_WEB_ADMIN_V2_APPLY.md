# BlinQ web/admin v2 — apply notes

This package implements the fixed-layout membership/content/admin architecture agreed for BlinQ.

## What is included

- ROOKIE / PRO / ELITE / GOAT + hidden LEGEND and separate ADMIN role.
- Automatic 72-hour Rookie trial.
- Fixed element IDs with ACTIVE / LOCKED / BLURRED / HIDDEN access rules.
- Three independent top header content slots.
- Eight large partner/content positions in two fixed four-unit rows.
- Row presets: 1+1+1+1, 2+2, 2+1+1, 1+1+2, 4.
- Content slot fallback: campaign/ad -> RSS/news -> internal/image fallback.
- Advertisers and campaigns managed separately from physical slots.
- Fixed 1-, 2- and 4-column campaign creative variants.
- Watermark toggle + editable text per banner.
- Elite/GOAT Hide Ads without collapsing layout.
- RSS source manager (normally 1–2 feeds).
- Campaign impressions, unique views, clicks, unique clicks and CTR.
- Admin account/plan assignment and plan preview.

## Runtime requirements

See `BLINQ_WEB_ADMIN_INSTALL.md`. Runtime admin config and analytics use Azure Table Storage. Supabase remains the account/authentication layer.

## Intentionally deferred

Player photo/rank/country enrichment is not wired in this package. Verified provider endpoint paths from the supplied screenshots are recorded in `PLAYER_ENRICHMENT_TODO.md` for the next pass.
