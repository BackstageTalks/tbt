# BlinQ v7.3.6-r10 repository cleanup audit

## Goal
Remove retired UI/runtime ballast without changing data-model semantics or the 7.3.6 production release identity.

## Removed runtime components
- VIP_RAIL and legacy four-card benefit strip
- VIP_TELEGRAM / FOOTBALL_ACCESS virtual leftovers
- BTTS beta dashboard/route/config shell
- SIDEBAR_PROMO_1..4 and dead right-rail promo carousel runtime
- dead dashboard right-rail match-detail runtime (the active match dialog remains)
- dynamic footer LIVE/data freshness widget and FOOTER_SYSTEM
- hidden legacy drawer/navigation DOM and JavaScript
- `web/config/footer-links.json`
- obsolete `home_small_banners` config
- obsolete static `blinq_loading_scene_v736.webp`

## CSS consolidation
The historical production stylesheet cascade was consolidated into one file, `web/blinq-app.css`. Retired selectors for the removed VIP rail, right rail, old system status and hidden desktop nav were pruned. Active banner image-fit/position rules were retained explicitly.

## Loader
`web/assets/blinq_loading_animated_v6.svg` is now a transparent vector loading scene with a real animated tennis-ball rally. It contains no embedded WebP screenshot/background square.

## Config/backend alignment
`web/ui-config.json` and `api/tbt/services/admin_storage.py` now validate only active banner/prediction/results inventory. Retired BTTS/sidebar/footer/VIP IDs are absent. `web/config/site-content.json` no longer carries unused dynamic footer status copy.

## Repository organization
Historical audit/release notes were moved from the project root to `docs/archive/`. Current root documentation is limited to the current base, current data-model reference and this cleanup audit.

## Release identity
- release: 7.3.6
- patch: 736-r10
- asset revision: 7360
- frontend marker: blinq-web-736
