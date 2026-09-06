# BlinQ membership, fixed UI access and content manager

This document describes the web/admin implementation added on 2026-09-06.

## Plans

- ROOKIE — €5.99/month, automatic 72-hour Rookie trial after registration.
- PRO — €14.99/month.
- ELITE — €99/year.
- GOAT — €199 lifetime.
- LEGEND — hidden/disabled reserve plan.
- ADMIN — separate role, never a subscription plan.

Trial access is derived from Supabase `created_at` and always inherits the Rookie UI rules. Paid/admin access lives in Supabase `app_metadata`, so a normal user cannot self-upgrade by editing `user_metadata`.

## Fixed layout contract

The page layout does not move according to plan. Every functional area has a stable element ID and a per-plan access state:

- `active`
- `locked`
- `blurred`
- `hidden` (geometry remains reserved)

The header shell/logo remain fixed. The three small header slots are separately configurable. The two external content rows each consist of four physical units.

Allowed row presets are deliberately limited to:

- `1+1+1+1`
- `2+2`
- `2+1+1`
- `1+1+2`
- `4`

Covered slot content is retained in configuration and returns when the row is switched back to a smaller preset.

## Content slots

Large external rows default to RSS/news fallback. A fixed slot can be configured as:

- advertisement
- RSS/news
- image
- internal BlinQ content
- promo

For ad inventory, slot, campaign and advertiser are logically separate objects. Assign a campaign to a slot in Admin; moving the campaign later does not change its campaign ID or analytics history.

Each banner can also have a single configurable watermark overlay, e.g. `COMING SOON`.

## Ads and RSS

ROOKIE/PRO see ads. ELITE/GOAT may enable Hide Ads. Hiding ads never collapses the layout; external ad creatives are replaced by RSS/image/internal fallback content.

RSS settings are editable in Admin and are stored in the same runtime UI configuration. One or two feeds are enough. The backend normalizes, freshness-filters and deduplicates headlines before returning them to the frontend.

## Analytics

Banner events are stored by campaign and slot. The frontend counts an impression only after at least 50% of the banner is in the viewport for about 1 second (configurable). Admin reports:

- impressions
- unique impressions
- clicks
- unique clicks
- CTR
- slots used by campaign

## Runtime storage

Live admin configuration and banner analytics use Azure Table Storage. By default the code uses `AzureWebJobsStorage`; alternatively set:

`BLINQ_ADMIN_STORAGE_CONNECTION_STRING`

Supabase remains the identity/account system. Admin account management also requires the existing server-only `SUPABASE_SERVICE_ROLE_KEY`.

The repository `web/ui-config.json` is the safe default/bootstrap configuration. Admin-published runtime configuration overrides it while retaining newly introduced default fields through a merge.

## Fixed advertising creative formats

Campaigns can store separate creative URLs/paths for the three supported large-slot widths. The frontend automatically chooses the variant matching the current fixed row preset:

- 1-column: 4:3, recommended 1200 × 900 px
- 2-column: 8:3, recommended 2400 × 900 px
- 4-column: 16:3, recommended 2400 × 450 px

A fallback image can also be supplied. Campaigns support a full-image mode (useful for advertiser-supplied finished banners) and a split mode where BlinQ headline/text/CTA may be rendered over or alongside the creative. The creative never changes the slot geometry.
